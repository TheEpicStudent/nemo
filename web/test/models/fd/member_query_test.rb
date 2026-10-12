require "test_helper"

class Fd::MemberQueryTest < ActiveSupport::TestCase
  def query(params = {})
    Fd::MemberQuery.new(ActionController::Parameters.new(params))
  end

  def named(user_ids)
    names_by_id = Fd::Member.where(user_id: user_ids)
      .pluck(:user_id, :display_name, :handle)
      .to_h { |id, display, handle| [id, (display.presence || handle.presence || id).downcase] }
    user_ids.map { |id| names_by_id.fetch(id, id.downcase) }
  end

  def collate(text)
    text.gsub(/[^a-z0-9]/, "")
  end

  def count_queries
    query_count = 0
    listener = ActiveSupport::Notifications.subscribe("sql.active_record") do |_, _, _, _, payload|
      query_count += 1 unless payload[:name].to_s.in?(%w[SCHEMA TRANSACTION])
    end
    yield
    query_count
  ensure
    ActiveSupport::Notifications.unsubscribe(listener)
  end

  setup do
    skip "no members to sort" if Fd::Member.live.count < 4
  end

  test "the two name directions are exact opposites" do
    forward = query("view" => "everyone", "sort" => "name").summary_rows.map(&:user_id)
    backward = query("view" => "everyone", "sort" => "name", "dir" => "asc")
      .summary_rows.map(&:user_id)

    assert_equal forward.reverse, backward,
      "one direction must be the other read backwards"
    assert_operator forward.size, :>, 1
  end

  test "the name sort groups people by the name they show, not their id" do
    names = named(query("view" => "everyone", "sort" => "name").rows.map(&:user_id))

    assert_equal names, names.sort { |a, b| collate(a) <=> collate(b) },
      "the page is not in the order the database collates names"
  end

  test "a page is the matching slice of the whole ordering" do
    params = { "view" => "everyone", "sort" => "name" }
    all_ids = query(params).summary_rows.map(&:user_id)

    assert_equal all_ids.first(Fd::MemberQuery::LIMIT), query(params).rows.map(&:user_id)
    assert_equal all_ids.slice(Fd::MemberQuery::LIMIT, Fd::MemberQuery::LIMIT),
      query(params.merge("page" => "2")).rows.map(&:user_id)
  end

  test "a page costs the same whether it is the first or a later one" do
    first_page_count = count_queries { query("view" => "everyone").rows }
    later_page_count = count_queries { query("view" => "everyone", "page" => "3").rows }

    assert_equal first_page_count, later_page_count, "a later page must not walk further than the first"
    assert_operator first_page_count, :<=, 2, "one count and one page, not a walk of the whole roster"
  end

  test "a page holds at most one page worth of people" do
    assert_operator query("view" => "everyone").rows.size, :<=, Fd::MemberQuery::LIMIT
  end

  test "the roster counts everybody the views claim" do
    counts = Fd::MemberQuery.view_counts

    assert_equal counts["everyone"], query("view" => "everyone").total
    assert_equal counts["open"], query("view" => "open").total
    assert_equal counts["notes"], query("view" => "notes").total
  end
end

class Fd::MemberQueryCountsCacheTest < ActiveSupport::TestCase
  setup do
    @store = Rails.cache
    Rails.cache = ActiveSupport::Cache::MemoryStore.new
  end

  teardown do
    Rails.cache = @store
  end

  test "view counts are computed once per cache window rather than once per request" do
    roster_passes = lambda do |&block|
      passes = 0
      listener = ActiveSupport::Notifications.subscribe("sql.active_record") do |_, _, _, _, payload|
        passes += 1 if payload[:sql].include?("conduct AS")
      end
      block.call
      passes
    ensure
      ActiveSupport::Notifications.unsubscribe(listener)
    end

    first = roster_passes.call { Fd::MemberQuery.new({}).views }
    second = roster_passes.call { Fd::MemberQuery.new({}).views }
    assert_equal 1, first
    assert_equal 0, second
  end
end

class Fd::MemberQueryDefaultSortTest < ActiveSupport::TestCase
  test "the list opens sorted by message count, busiest first, people without a count last" do
    query = Fd::MemberQuery.new({})
    assert_equal "messages", query["sort"]
    assert_equal "most messages", query.sort_label

    counts = query.rows.map(&:messages_posted)
    known = counts.compact
    assert_equal known.sort.reverse, known, "rows with a count come in descending order"
    assert_equal counts.compact + [nil] * counts.count(nil), counts, "unknown counts sit at the end"
  end
end

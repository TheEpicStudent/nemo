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

  test "summary_rows with dir asc reverses the default name order" do
    forward = query("view" => "everyone", "sort" => "name").summary_rows.map(&:user_id)
    backward = query("view" => "everyone", "sort" => "name", "dir" => "asc")
      .summary_rows.map(&:user_id)

    assert_equal forward.reverse, backward,
      "dir asc is the reverse of the default order"
    assert_operator forward.size, :>, 1
  end

  test "rows with name sort order by displayed name" do
    names = named(query("view" => "everyone", "sort" => "name").rows.map(&:user_id))

    assert_equal names, names.sort { |a, b| collate(a) <=> collate(b) },
      "rows are not ordered by displayed name"
  end

  test "rows for page 1 and 2 match slices of summary_rows" do
    params = { "view" => "everyone", "sort" => "name" }
    all_ids = query(params).summary_rows.map(&:user_id)

    assert_equal all_ids.first(Fd::MemberQuery::LIMIT), query(params).rows.map(&:user_id)
    assert_equal all_ids.slice(Fd::MemberQuery::LIMIT, Fd::MemberQuery::LIMIT),
      query(params.merge("page" => "2")).rows.map(&:user_id)
  end

  test "rows runs the same number of queries for page 1 and page 3" do
    first_page_count = count_queries { query("view" => "everyone").rows }
    later_page_count = count_queries { query("view" => "everyone", "page" => "3").rows }

    assert_equal first_page_count, later_page_count, "page 3 query count equals page 1"
    assert_operator first_page_count, :<=, 2, "at most two queries per page"
  end

  test "rows returns at most LIMIT rows" do
    assert_operator query("view" => "everyone").rows.size, :<=, Fd::MemberQuery::LIMIT
  end

  test "total matches view_counts for everyone open and notes" do
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

  test "views runs the roster query once across repeated calls with a cache" do
    count_roster_queries = lambda do |&block|
      roster_queries = 0
      listener = ActiveSupport::Notifications.subscribe("sql.active_record") do |_, _, _, _, payload|
        roster_queries += 1 if payload[:sql].include?("conduct AS")
      end
      block.call
      roster_queries
    ensure
      ActiveSupport::Notifications.unsubscribe(listener)
    end

    first = count_roster_queries.call { Fd::MemberQuery.new({}).views }
    second = count_roster_queries.call { Fd::MemberQuery.new({}).views }
    assert_equal 1, first
    assert_equal 0, second
  end
end

class Fd::MemberQueryDefaultSortTest < ActiveSupport::TestCase
  test "default sort is messages descending with nil counts last" do
    query = Fd::MemberQuery.new({})
    assert_equal "messages", query["sort"]
    assert_equal "most messages", query.sort_label

    counts = query.rows.map(&:messages_posted)
    known = counts.compact
    assert_equal known.sort.reverse, known, "rows with a count come in descending order"
    assert_equal counts.compact + [nil] * counts.count(nil), counts, "unknown counts sit at the end"
  end
end

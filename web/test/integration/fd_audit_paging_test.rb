require "test_helper"

class FdAuditPagingTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
    @base = Time.zone.parse("2026-10-01 12:00")
    @ids = (1..250).map do |minute|
      id = SecureRandom.uuid
      as_pipeline(<<~SQL.squish, id, @base - minute.minutes)
        INSERT INTO slack.audit_event (id, at, action, category, actor_kind, actor_id, ours, payload, source_key)
        VALUES (?::uuid, ?, 'user_login', 'sign_ins', 'user', 'UPAGE', false, '{}', 'test')
      SQL
      seeded!("slack.audit_event", "id", id)
      id
    end
  end

  def page(params = {})
    Fd::AuditQuery.new({ "view" => "slack" }.merge(params), actor: @me)
  end

  test "back_params steps back through the pages returned by next_params" do
    first = page
    assert_nil first.back_params
    second = page(first.next_params)
    third = page(second.next_params)

    previous_page = page(third.back_params)
    assert_equal second.rows.map(&:id), previous_page.rows.map(&:id)
    assert page(previous_page.back_params).rows.map(&:id) == first.rows.map(&:id)
  end

  test "back_params from the second page returns the first page with nil back_params" do
    first = page
    second = page(first.next_params)
    previous_page = page(second.back_params)

    assert_equal first.rows.map(&:id), previous_page.rows.map(&:id)
    assert_nil previous_page.back_params
  end

  test "on param shows the newest events up to the end of that day" do
    dated_page = page("on" => "2026-10-01")
    assert_equal @ids.first(100), dated_page.rows.map(&:id)

    assert_empty page("on" => "2026-09-30").rows, "a day before every event returns no rows"
  end

  test "audit page renders back and next controls and a date picker" do
    get fd_audit_path(view: "slack")
    assert_select ".pagebar span.is-off", "Back"
    assert_select ".pagebar a", "Next"
    assert_select ".pagebar [data-controller='datepicker'][data-datepicker-submit-value='true'] input[name='on']"

    get fd_audit_path(page.next_params)
    assert_select ".pagebar a", "Back"
  end
end

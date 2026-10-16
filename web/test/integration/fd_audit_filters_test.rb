require "test_helper"

class FdAuditFiltersTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def slack!(action, category)
    id = SecureRandom.uuid
    as_pipeline(<<~SQL.squish, id, action, category)
      INSERT INTO slack.audit_event (id, at, action, category, actor_kind, actor_id, ours, payload, source_key)
      VALUES (?::uuid, now() - interval '1 hour', ?, ?, 'user', 'UFILTER', false, '{}', 'test')
    SQL
    seeded!("slack.audit_event", "id", id)
  end

  def slim!(code)
    id = SecureRandom.uuid
    as_pipeline("INSERT INTO slack.audit_view (id, at, action, actor_id, object_id) " \
                "VALUES (?::uuid, now() - interval '2 hours', ?, 'UFILTER', 'F0FILE')", id, code)
    seeded!("slack.audit_view", "id", id)
  end

  def query(term, view: "everything")
    Fd::AuditQuery.new({ "view" => view, "q" => term }, actor: @me)
  end

  test "audit query with category filter returns only matching slack events" do
    slack!("user_login", "sign_ins")
    slack!("channel_created", "channels")
    Fd::AuditEntry.create!(occurred_at: 1.hour.ago, actor_user_id: "UME", actor_kind: "human",
      entity_type: "case", entity_id: 1, verb: "opened", source_app: "fire_engine")

    rows = query("category:sign_ins").rows
    assert_equal %w[user_login], rows.map(&:verb)
  end

  test "audit search parse resolves category label and drops unknown category" do
    term = Fd::AuditSearch.parse("category:Huddles").terms.first
    assert_equal ["category", "huddles", "Huddles"], [term.kind, term.value, term.label]
    assert_empty Fd::AuditSearch.parse("category:nonsense").terms
  end

  test "audit query set_params replaces term of same kind and keeps others" do
    audit_query = query("category:people did:user_login @UFILTER", view: "slack")

    params = audit_query.set_params("category", "channels")
    assert_equal "action:user_login about:UFILTER category:channels", params["q"]
    assert_equal({ "q" => "action:user_login about:UFILTER" }, audit_query.set_params("category"))
  end

  test "audit index with category filter renders category summary and one menu group" do
    get fd_audit_path(q: "category:huddles")
    assert_response :success

    assert_select ".audit-filters summary", text: /Category\s*Huddles/
    assert_select ".audit-filters .menu-group", 1
    assert_select ".audit-filters .menu-group", "Huddles"
    assert_select ".audit-filters a[aria-current='true']", text: "Huddles"
  end

  test "audit index renders time presets with is:human link and last:7d token" do
    get fd_audit_path

    assert_select ".audit-filters .daterange a[href*='last%3A24h']", "Last 24 hours"
    assert_select ".audit-filters .daterange a[href*='last%3A7d']", "Last 7 days"
    assert_select ".audit-filters .daterange form[action='#{fd_audit_path}']"
    assert_select ".audit-filters a[href*='is%3Ahuman']", text: /Human/

    get fd_audit_path(q: "last:7d")
    assert_select ".audit-filters .daterange-presets summary", text: /Last 7 days/
    assert_select ".audit-token", text: /last:\s*7d/
  end

  test "audit index with start and end params redirects to after and before terms" do
    get fd_audit_path(q: "did:user_login after:2026-01-01", start: "2026-10-01", end: "2026-10-03")

    assert_redirected_to fd_audit_path(q: "action:user_login after:2026-10-01 before:2026-10-04")
    follow_redirect!
    assert_select ".audit-filters .daterange-presets summary", text: /Custom/
    assert_select ".daterange-open", text: /Oct 1 - Oct 3, 2026/
  end

  test "audit query hides high-volume actions unless show:high_volume" do
    slack!("user_login", "sign_ins")
    slim!(3)
    slim!(4)
    slim!(2)

    assert_equal %w[user_login], query("", view: "slack").rows.map(&:verb)

    verbs = query("show:high_volume", view: "slack").rows.map(&:verb)
    assert_equal %w[canvas_opened file_downloaded list_cell_updated user_login], verbs.sort
  end

  test "audit query with show:high_volume and category returns only that category" do
    slim!(3)
    slim!(4)
    slim!(2)

    rows = query("show:high_volume category:canvases_and_lists", view: "slack").rows
    assert_equal %w[canvas_opened list_cell_updated], rows.map(&:verb).sort
  end

  test "audit index high-volume toggle shows state and link to opposite term" do
    get fd_audit_path
    assert_select ".audit-filters summary", text: /High-volume\s*Hidden/
    assert_select ".audit-filters a[href*='show%3Ahigh_volume']", "Shown"

    get fd_audit_path(q: "show:high_volume")
    assert_select ".audit-filters summary", text: /High-volume\s*Shown/
    assert_select ".audit-token", text: /show:\s*high_volume/
  end
end

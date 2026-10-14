require "test_helper"

class FdMemberTabsTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  WHO = "UTABWHO".freeze
  OTHER = "UTABOTHER".freeze

  setup do
    @boss = hold_role!("UTABBOSS", "community_manager")
    sign_in_as(@boss)
  end

  def slack!(actor:, entity: nil, action: "user_login", at: 1.hour.ago)
    id = SecureRandom.uuid
    as_pipeline(<<~SQL.squish, id, at, action, actor, entity, { id: id }.to_json)
      INSERT INTO slack.audit_event (id, at, action, actor_kind, actor_id, entity_kind, entity_id, ours, payload, source_key)
      VALUES (?::uuid, ?, ?, 'user', ?, 'user', ?, false, ?::jsonb, 'test')
    SQL
    seeded!("slack.audit_event", "id", id)
    id
  end

  def member_dim!(user_id, **columns)
    values = { invite_pending: false, claimed_at: nil, is_deleted: false }.merge(columns)
    as_pipeline("INSERT INTO raw.member_dim (user_id, invite_pending, claimed_at, is_deleted) VALUES (?, ?, ?, ?)",
      user_id, values[:invite_pending], values[:claimed_at], values[:is_deleted])
    seeded!("raw.member_dim", "user_id", user_id)
  end

  def tab_labels
    css_select("nav.member-record-tabs a.view").map { |link| link.at("span").text.squish }
  end

  test "the record is split into tabs, history first" do
    get fd_member_path(WHO)

    assert_equal ["History", "Linked accounts", "Sessions", "Audit", "Enforcement", "Purges"], tab_labels
    assert_select "nav.member-record-tabs a[aria-current=true]", text: /History/
    assert_select "turbo-frame#member-record[target=_top]"
    assert_select %(nav.member-record-tabs a[href="#{fd_member_path(WHO, tab: "audit")}"][data-turbo-frame="member-record"][data-turbo-action="advance"])
  end

  test "linked accounts and sessions need their own capabilities" do
    firefighter = hold_role!("UTABFF", "firefighter")
    move_capability!("firefighter", "member.links", false, by: "UTABBOSS")
    move_capability!("firefighter", "identity.read", false, by: "UTABBOSS")
    sign_in_as(firefighter)

    get fd_member_path(WHO, tab: "sessions")

    assert_equal %w[History Audit Enforcement Purges], tab_labels
    assert_select "nav.member-record-tabs a[aria-current=true]", text: /History/
  end

  test "the old do=links address opens the linked accounts tab" do
    get fd_member_path(WHO, do: "links")

    assert_select "nav.member-record-tabs a[aria-current=true]", text: /Linked accounts/
    assert_select %(turbo-frame#member-links-#{WHO}[src="#{fd_member_links_path(WHO)}"][loading=lazy])
  end

  test "the audit tab lists events by and about the member, each opening in the audit log" do
    by_them = slack!(actor: WHO)
    about_them = slack!(actor: OTHER, entity: WHO, action: "user_profile_updated", at: 2.hours.ago)
    slack!(actor: OTHER, entity: "UTABNOBODY")

    get fd_member_path(WHO, tab: "audit")

    search = { view: "everything", q: "about:#{WHO} source:slack source:engine" }
    hrefs = css_select("a.member-audit-row").map { |link| link["href"] }
    assert_equal [fd_audit_path(search.merge(event: "slack:#{by_them}")), fd_audit_path(search.merge(event: "slack:#{about_them}"))], hrefs
    assert_select ".member-tab-head a[href=?]", fd_audit_path(search)
    assert_select ".member-tab-head .sub2", "2 events"
  end

  test "about: in the audit log matches the actor or the target" do
    slack!(actor: WHO)
    slack!(actor: OTHER, entity: WHO)
    slack!(actor: OTHER, entity: "UTABNOBODY")

    rows = Fd::AuditQuery.new({ "q" => "about:#{WHO}", "view" => "everything" }, actor: @boss).rows

    assert_equal 2, rows.size
  end

  test "the enforcement tab lists every guard, lifted ones included" do
    Fd::MemberGuard.create!(kind: "shush", subject_id: WHO, opened_by: "UTABBOSS", reason: "spam in lounge",
      expires_at: 5.days.from_now)
    Fd::MemberGuard.create!(kind: "shush", subject_id: WHO, opened_by: "UTABBOSS", reason: "old spam",
      opened_at: 40.days.ago, state: "lifted", lifted_at: 30.days.ago, lifted_by: "UTABBOSS")

    get fd_member_path(WHO, tab: "enforcement")

    reasons = css_select(".member-tab table tbody tr").map { |row| row.css("td")[1].text.squish }
    assert_equal ["spam in lounge", "old spam"], reasons
    assert_select ".member-tab td", text: /\ALifted /
  end

  test "an empty tab is a bare title" do
    get fd_member_path(WHO, tab: "enforcement")

    assert_select ".member-tab .empty-title", "No guards"
  end

  test "the hero names the Slack account state" do
    member_dim!(WHO, invite_pending: true)
    get fd_member_path(WHO)
    assert_select ".member-hero-sub .state.state-warn", "Invite pending"

    member_dim!(OTHER, claimed_at: 2.days.ago)
    get fd_member_path(OTHER)
    assert_select ".member-hero-sub .state", "Claimed, no sign-in"
  end

  test "a claimed account with a sign-in is active" do
    member_dim!(WHO, claimed_at: 2.days.ago)
    as_pipeline("INSERT INTO fd.member_seen (user_id, last_login_at) VALUES (?, now())", WHO)
    seeded!("fd.member_seen", "user_id", WHO)

    get fd_member_path(WHO)

    assert_select ".member-hero-sub .state.state-good", "Active"
  end

  test "an account claimed before sign-ins were recorded is not called unused" do
    member_dim!(WHO, claimed_at: Time.utc(2024, 1, 1))

    get fd_member_path(WHO)

    assert_select ".member-hero-sub .state", false
  end
end

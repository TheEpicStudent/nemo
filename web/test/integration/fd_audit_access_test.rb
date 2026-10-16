require "test_helper"

class FdAuditAccessTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  ACTOR_ID = "UAUDWHO".freeze
  IP = "81.2.69.144".freeze
  EMAIL = "kid@alts.example".freeze

  setup do
    grant_role!("UBOSS", "community_manager")
    @ff = grant_role!("UFFAUD", "firefighter")
    sign_in_as(@ff)
  end

  def slack!(action: "user_login", actor: ACTOR_ID, at: 1.hour.ago)
    id = SecureRandom.uuid
    as_pipeline(<<~SQL.squish, id,
      INSERT INTO slack.audit_event (id, at, action, actor_kind, actor_id, actor_email,
                                     entity_kind, entity_id, ours, ip, payload, source_key)
      VALUES (?::uuid, ?, ?, 'user', ?, ?, 'user', ?, false, ?::inet, ?::jsonb, 'test')
    SQL
      at, action, actor, EMAIL, actor, IP,
      { id: id, action: action, context: { ip_address: IP },
        actor: { type: "user", user: { id: actor, email: EMAIL, name: "kid" } },
        entity: { type: "file", file: { title: EMAIL } } }.to_json)
    seeded!("slack.audit_event", "id", id)
    id
  end

  def access_log_subjects(field_class)
    AccessLog.where(actor_id: @ff.user_id, field_class: field_class).pluck(:subject_user_id)
  end

  test "audit index with audit.read shows slack tab with rows and filters" do
    slack!

    get fd_audit_path
    assert_response :success
    assert_select ".view[aria-current=true]", /Slack/
    assert_match(/user login/, response.body)
    assert_select ".audit-filters", text: /Category/
  end

  test "audit index without audit.read hides slack tab with rows and filters" do
    slack!
    override_capability!("firefighter", "audit.read", false, by: "UBOSS")

    get fd_audit_path
    assert_response :success
    assert_select ".view", text: /Slack/, count: 0
    assert_select ".view[aria-current=true]", /All/
    assert_no_match(/user login/, response.body)
    assert_select ".audit-filters", text: /Category/, count: 0
    assert_select ".audit-filters", text: /High-volume/, count: 0

    get fd_audit_path(view: "slack", q: "source:slack")
    assert_no_match(/user login/, response.body)
  end

  test "audit event show for slack without audit.read returns 403" do
    id = slack!
    override_capability!("firefighter", "audit.read", false, by: "UBOSS")

    get fd_audit_event_path(source: "slack", id: id)
    assert_response :forbidden
  end

  test "nav shows audit link only with audit.read" do
    get fd_cases_path
    assert_select "a[href='#{fd_audit_path}']"

    override_capability!("firefighter", "audit.read", false, by: "UBOSS")
    get fd_cases_path
    assert_select "a[href='#{fd_audit_path}']", count: 0
  end

  test "audit index and event without identity.read hide addresses and emails" do
    id = slack!
    override_capability!("firefighter", "identity.read", false, by: "UBOSS")

    get fd_audit_path
    assert_match(/user login/, response.body)
    assert_no_match(IP, response.body)
    assert_no_match(EMAIL, response.body)

    get fd_audit_event_path(source: "slack", id: id)
    assert_response :success
    assert_no_match(IP, response.body)
    assert_no_match(EMAIL, response.body)
    assert_select "dt", text: "Address", count: 0
    assert_match(/hidden/, response.body)
    assert_no_match(/&quot;kid&quot;|"kid"/, response.body)
  end

  test "audit event with identity.read shows address and email" do
    id = slack!

    get fd_audit_event_path(source: "slack", id: id)
    assert_match(IP, response.body)
    assert_match(EMAIL, response.body)
  end

  test "audit search by identity term without identity.read shows requirement and logs nothing" do
    slack!
    override_capability!("firefighter", "identity.read", false, by: "UBOSS")

    [IP, EMAIL, "domain:alts.example", "text:#{IP}"].each do |search|
      get fd_audit_path(q: search)
      assert_response :success
      assert_select ".empty-title", "Requires identity.read"
      assert_no_match(/user login/, response.body)
    end
    assert_empty access_log_subjects("identity_search")
  end

  test "audit search by address logs identity_search access for matched actors" do
    slack!
    slack!(actor: "UAUDOTHER")

    get fd_audit_path(q: IP)
    assert_match(/user login/, response.body)
    assert_equal [ACTOR_ID, "UAUDOTHER"].sort, access_log_subjects("identity_search").sort

    get fd_audit_path(q: "invite spam")
    assert_equal 2, access_log_subjects("identity_search").size
  end

  test "audit search with actor logs audit access for that actor" do
    slack!

    get fd_audit_path(q: "actor:#{ACTOR_ID}")
    assert_equal [ACTOR_ID], access_log_subjects("audit")

    get fd_audit_path
    assert_equal [ACTOR_ID], access_log_subjects("audit")
  end

  test "audit reads view search about user logs no audit access" do
    get fd_audit_path(view: "reads", q: "about:#{ACTOR_ID}")
    assert_empty access_log_subjects("audit")
  end
end

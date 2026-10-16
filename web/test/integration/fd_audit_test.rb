require "test_helper"

class FdAuditTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables
  USER_ID = "USUB".freeze

  setup do
    @me = grant_role!("UME", "community_manager")
  end

  def engine!(verb: "opened", actor: "UME", kind: "human", entity: "case", id: 1,
    subject: nil, before: nil, after: nil, at: 1.hour.ago)
    Fd::AuditEntry.create!(occurred_at: at, actor_user_id: actor, actor_kind: kind,
      entity_type: entity, entity_id: id, verb: verb, subject_user_id: subject,
      before: before, after: after, source_app: "fire_engine")
  end

  def slack!(action: "user_login", actor: USER_ID, at: 1.hour.ago, ip: "81.2.69.144",
    id: SecureRandom.uuid, ours: false, email: nil)
    as_pipeline(<<~SQL.squish, id,
      INSERT INTO slack.audit_event (id, at, action, actor_kind, actor_id, actor_email,
                                     entity_kind, entity_id, ours, ip, payload, source_key)
      VALUES (?::uuid, ?, ?, 'user', ?, lower(?), 'user', ?, ?, ?::inet, ?::jsonb, 'test')
    SQL
      at, action, actor, email, actor, ours, ip,
      { id: id, action: action, context: { ip_address: ip },
        actor: { type: "user", user: { id: actor, email: email }.compact } }.to_json)
    seeded!("slack.audit_event", "id", id)
  end

  VIEW_CODES = { "public_channel_preview" => 1, "file_downloaded" => 3 }.freeze

  def slim!(action: "file_downloaded", actor: USER_ID, object: "F0FILE01", at: 1.hour.ago,
    ip: "81.2.69.144", ours: false)
    id = SecureRandom.uuid
    as_pipeline(<<~SQL.squish, id, at, VIEW_CODES.fetch(action), actor, object, ip, ours)
      INSERT INTO slack.audit_view (id, at, action, actor_id, object_id, ip, ours)
      VALUES (?::uuid, ?, ?, ?, ?, ?::inet, ?)
    SQL
    seeded!("slack.audit_view", "id", id)
  end

  def query(params = {})
    Fd::AuditQuery.new({ "view" => "everything" }.merge(params.stringify_keys), actor: @me)
  end

  test "everything view includes fire_engine and slack rows" do
    engine!(verb: "resolved")
    slack!(action: "user_login")

    sources = query.rows.map(&:source).uniq
    assert_includes sources, "fire_engine"
    assert_includes sources, "slack"
  end

  test "view param limits rows to one source and keeps other view counts" do
    engine!
    slack!
    AccessLog.record!(actor: @me, subject_user_id: USER_ID, field_class: "identity")

    assert_equal ["fire_engine"], query("view" => "engine").rows.map(&:source).uniq
    assert_equal ["slack"], query("view" => "slack").rows.map(&:source).uniq
    assert_equal ["read"], query("view" => "reads").rows.map(&:source).uniq

    counts = query("view" => "slack").views.index_by(&:key)
    assert_equal 1, counts["engine"].count, "a tab must not narrow the other tabs' counts"
    assert_equal 1, counts["reads"].count
  end

  test "slack view excludes events and views with ours true" do
    slack!(action: "user_profile_updated", ours: true)
    slack!(action: "user_login", ours: false)
    slim!(action: "public_channel_preview", ours: true)

    assert_equal %w[user_login], query("view" => "slack").rows.map(&:verb)
    assert_empty query("view" => "slack", "q" => "did:public_channel_preview").rows
  end

  test "slack view includes high volume reads only for a did: filter" do
    slack!(action: "user_login")
    slim!(action: "file_downloaded", object: "F0FILE01", ip: "86.12.44.9")

    assert_equal %w[user_login], query("view" => "slack").rows.map(&:verb)

    rows = query("view" => "slack", "q" => "did:file_downloaded").rows
    assert_equal %w[file_downloaded], rows.map(&:verb)
    assert_equal "F0FILE01", rows.first.entity_id
    assert_equal "86.12.44.9", rows.first.ip
  end

  test "find_one returns audit_view row with verb and actor_id" do
    id = slim!(action: "file_downloaded")

    row = Fd::AuditQuery.find_one("slack", id)
    assert_equal "file_downloaded", row.verb
    assert_equal USER_ID, row.actor_id
  end

  test "migration 0192 gin index uses the SLACK_SEARCHED expression" do
    sql = Rails.root.join("../db/migrations/0192_move_audit_events.sql").read.squish
    assert_includes sql, "USING gin (( #{Fd::AuditQuery::SLACK_SEARCHED} ))"
  end

  test "refusals view lists refused rows and engine view excludes them" do
    engine!(verb: "refused", entity: "permission")
    engine!(verb: "opened")

    assert_equal %w[refused], query("view" => "refusals").rows.map(&:verb)
    assert_not_includes query("view" => "engine").rows.map(&:verb), "refused"
  end

  test "query returns rows of any age and filters by before: and after:" do
    engine!(verb: "opened", at: 2.hours.ago)
    engine!(verb: "resolved", at: 3.years.ago)

    assert_equal 2, query.rows.size
    assert_equal %w[resolved], query("q" => "before:#{2.years.ago.to_date}").rows.map(&:verb)
    assert_equal %w[opened], query("q" => "after:#{1.year.ago.to_date}").rows.map(&:verb)
  end

  test "free text q matches values inside the after json" do
    engine!(verb: "categorised", after: { "category_key" => "harassment" })
    engine!(verb: "opened", after: { "category_key" => "spam" })

    assert_equal %w[categorised], query("q" => "harassment").rows.map(&:verb)
  end

  test "q with an IP returns the slack event with that ip" do
    slack!(ip: "203.0.113.9")
    slack!(ip: "198.51.100.4", id: SecureRandom.uuid)

    rows = query("q" => "203.0.113.9").rows
    assert_equal 1, rows.size
    assert_equal "203.0.113.9", rows.first.ip
  end

  test "about: filter matches engine subject and slack actor" do
    engine!(subject: USER_ID, verb: "performed")
    engine!(subject: "UOTHER", verb: "noted")
    slack!(actor: USER_ID)

    rows = query("q" => "about:#{USER_ID}").rows
    assert_equal %w[performed user_login].sort, rows.map(&:verb).sort
  end

  test "did: filter returns rows with that verb" do
    engine!(verb: "opened")
    engine!(verb: "resolved")

    assert_equal %w[resolved], query("q" => "did:resolved").rows.map(&:verb)
  end

  test "is:person returns human actors and is:nemo returns bot actors" do
    engine!(actor: "UME", kind: "human", verb: "opened")
    engine!(actor: nil, kind: "bot", verb: "lifted")

    assert_equal %w[opened], query("q" => "is:person").rows.map(&:verb)
    assert_equal %w[lifted], query("q" => "is:nemo").rows.map(&:verb)
  end

  test "before_at and before_id from the last row return an empty next page" do
    3.times { |n| engine!(verb: "opened", id: n + 1, at: (n + 1).hours.ago) }

    first = query
    assert_not_nil first.rows.last
    next_page_params = first.to_params.merge("before_at" => first.rows.last.at.iso8601(6),
      "before_id" => first.rows.last.id)
    assert_empty Fd::AuditQuery.new(next_page_params, actor: @me).rows
  end

  test "row with before and after exposes diff? changed_keys was and now" do
    engine!(verb: "categorised", before: { "category_key" => "spam" },
      after: { "category_key" => "harassment" })

    row = query.rows.first
    assert row.diff?
    assert_equal %w[category_key], row.changed_keys
    assert_equal "spam", row.was("category_key")
    assert_equal "harassment", row.now("category_key")
  end

  test "slack row diff? is false" do
    slack!

    assert_not query("view" => "slack").rows.first.diff?
  end

  test "audit page renders table with resolved and user login rows" do
    engine!(verb: "resolved")
    slack!
    sign_in_as(@me)

    get fd_audit_path
    assert_response :success
    assert_select ".audit-table"
    assert_match "resolved", response.body
    assert_match "user login", response.body
  end

  test "q with an IP excludes another actor event on a different IP" do
    slack!(ip: "86.12.44.9", actor: USER_ID)
    slack!(ip: "198.51.100.4", actor: "UOTHER", id: SecureRandom.uuid)

    rows = query("q" => "86.12.44.9").rows
    assert_equal 1, rows.size
    assert_equal "86.12.44.9", rows.first.ip
  end

  test "ip: CIDR filter returns events inside the range" do
    slack!(ip: "86.12.44.9")
    slack!(ip: "86.12.44.200", id: SecureRandom.uuid)
    slack!(ip: "198.51.100.4", id: SecureRandom.uuid)

    assert_equal 2, query("q" => "ip:86.12.44.0/24").rows.size
  end

  test "q with member email and domain: return engine rows about that member" do
    member!(USER_ID, email: "kid@school.example")
    engine!(subject: USER_ID, verb: "performed")
    engine!(subject: "UOTHER", verb: "noted")

    assert_equal %w[performed], query("q" => "kid@school.example").rows.map(&:verb)
    assert_equal %w[performed], query("q" => "domain:school.example").rows.map(&:verb)
  end

  test "q email and domain: match slack actor_email without a member" do
    slack!(email: "kid@throwaway.example", actor: "UKID")
    slack!(email: "someone@else.example", actor: "UELSE", id: SecureRandom.uuid)

    assert_equal 1, query("q" => "kid@throwaway.example").rows.size
    assert_equal 1, query("q" => "domain:throwaway.example").rows.size
  end

  test "domain: with a full email parses to the domain and matches" do
    slack!(email: "kid@throwaway.example", actor: "UKID")

    search = Fd::AuditSearch.parse("domain:kid@throwaway.example")
    assert_equal [["domain", "throwaway.example"]], search.terms.map { |term| [term.kind, term.value] }
    assert_equal 1, query("q" => "domain:kid@throwaway.example").rows.size
  end

  test "email: with a bare domain parses to a domain term" do
    search = Fd::AuditSearch.parse("email:throwaway.example")
    assert_equal [["domain", "throwaway.example"]], search.terms.map { |term| [term.kind, term.value] }
  end

  test "email q with no actor returns no rows" do
    engine!(subject: USER_ID, verb: "performed")

    anonymous_query = Fd::AuditQuery.new({ "when" => "any", "q" => "kid@school.example" }, actor: nil)
    assert_empty anonymous_query.rows
  end

  test "bare term parses as text kind and matches after values" do
    engine!(verb: "categorised", after: { "category_key" => "harassment" })

    parsed = Fd::AuditSearch.parse("harassment")
    assert_equal %w[text], parsed.terms.map(&:kind)
    assert_equal %w[categorised], query("q" => "harassment").rows.map(&:verb)
  end

  test "without_params removes one term and keeps the others" do
    audit_query = query("q" => "about:#{USER_ID} did:resolved")
    first = audit_query.terms.first

    remaining_query = audit_query.without_params(first)["q"]
    assert_not_includes remaining_query.to_s, first.value
    assert_includes remaining_query.to_s, "resolved"
  end

  test "audit page marks slack view current and renders no range control" do
    sign_in_as(@me)

    get fd_audit_path
    assert_select %(.view[aria-current="true"]), text: /Slack/
    assert_select "main .segmented", false, "range control absent"
    assert_select ".toolbar .audit-query input[name=add]"
  end

  test "audit page renders help modal and open button with examples" do
    sign_in_as(@me)

    get fd_audit_path
    assert_select %(button[data-modal-open="audit-help"])
    assert_select "#audit-help.modal-flip"
    assert_select ".audit-help-try", minimum: 5
  end

  test "audit page omits raw payload and event path renders it in panel" do
    id = SecureRandom.uuid
    slack!(id: id, action: "user_profile_updated")
    sign_in_as(@me)

    get fd_audit_path
    assert_select %(a[data-turbo-frame="audit-panel"]), 1
    assert_select "turbo-frame#audit-panel"
    assert_no_match(/audit-panel-raw/, response.body, "table does not include raw payload")

    get fd_audit_event_path(source: "slack", id: id)
    assert_response :success
    assert_select "turbo-frame#audit-panel .audit-panel-raw"
    assert_match "user_profile_updated", response.body
  end

  test "event path returns 404 for unknown id and unknown source" do
    sign_in_as(@me)

    get fd_audit_event_path(source: "slack", id: SecureRandom.uuid)
    assert_response :not_found

    get fd_audit_event_path(source: "nonsense", id: "1")
    assert_response :not_found
  end

  test "event path for fire_engine entry renders verb and changed values" do
    entry = engine!(verb: "resolved", before: { "resolution" => nil },
      after: { "resolution" => "warned" })
    sign_in_as(@me)

    get fd_audit_event_path(source: "fire_engine", id: entry.id.to_s)
    assert_response :success
    assert_match "resolved", response.body
    assert_match "warned", response.body
  end

  def in_channel!(channel_id, action: "user_channel_join")
    id = SecureRandom.uuid
    as_pipeline(<<~SQL.squish,
      INSERT INTO slack.audit_event (id, at, action, actor_kind, actor_id, entity_kind,
                                     entity_id, channel_id, ours, payload, source_key)
      VALUES (?::uuid, now(), ?, 'user', ?, 'channel', ?, ?, false, '{}'::jsonb, 'test')
    SQL
      id, action, USER_ID, channel_id, channel_id)
    seeded!("slack.audit_event", "id", id)
  end

  def named_channel!(channel_id, name)
    as_pipeline(<<~SQL.squish,
      INSERT INTO raw.channel_dim (channel_id, name, visibility)
      VALUES (?, ?, 'public')
      ON CONFLICT (channel_id) DO UPDATE SET name = EXCLUDED.name
    SQL
      channel_id, name)
    seeded!("raw.channel_dim", "channel_id", channel_id)
  end

  test "audit page links a known channel as #name to its channel page" do
    named_channel!("C0APH2MMHH7", "ask")
    in_channel!("C0APH2MMHH7")
    sign_in_as(@me)

    get fd_audit_path
    assert_select %(a[href="/channels/C0APH2MMHH7"]), text: "#ask"
    assert_no_match(/channel C0APH2MMHH7/, response.body)
  end

  test "audit page renders unknown channel as #private-channel without link" do
    in_channel!("C0PRIVATE01")
    sign_in_as(@me)

    get fd_audit_path
    assert_select %(a[href*="C0PRIVATE01"]), false
    assert_match "#private-channel", response.body
  end

  test "firefighter everything view renders slack rows and no engine rows" do
    engine!(verb: "resolved")
    slack!
    AccessLog.record!(actor: @me, subject_user_id: USER_ID, field_class: "identity")
    sign_in_as(grant_role!("UFF", "firefighter"))

    get fd_audit_path(view: "everything")
    assert_response :success
    assert_select ".audit-verb", text: "resolved", count: 0
    assert_select ".audit-verb", text: "user login"
  end

  test "firefighter audit page lists Slack view and no Fire Engine views" do
    sign_in_as(grant_role!("UFF", "firefighter"))

    get fd_audit_path
    assert_select ".view", text: /Slack/
    assert_select ".view", text: /Fire Engine/, count: 0
    assert_select ".view", text: /Access denied/, count: 0
  end

  test "firefighter query with view engine falls back to slack and no rows" do
    engine!(verb: "resolved")
    firefighter = grant_role!("UFF", "firefighter")
    audit_query = Fd::AuditQuery.new({ "view" => "engine" }, actor: firefighter)

    assert_equal "slack", audit_query.view
    assert_empty audit_query.rows
    assert_empty Fd::AuditQuery.new({ "q" => "source:engine" }, actor: firefighter).rows
  end

  test "firefighter event path for fire_engine returns 403" do
    entry = engine!(verb: "resolved")
    sign_in_as(grant_role!("UFF", "firefighter"))

    get fd_audit_event_path(source: "fire_engine", id: entry.id.to_s)
    assert_response :forbidden
  end

  test "community manager everything view renders engine and slack rows" do
    engine!(verb: "resolved")
    slack!
    sign_in_as(@me)

    get fd_audit_path(view: "everything")
    assert_select ".audit-verb", text: "resolved"
    assert_select ".view", text: /Fire Engine/
  end

  test "count_sql and counting_sql select only source" do
    query = Fd::AuditQuery.new({}, actor: @me)

    [query.send(:count_sql), query.send(:counting_sql)].each do |sql|
      assert_match(/SELECT source FROM \(/, sql,
        "count query selects only source")
      assert_no_match(/SELECT \* FROM \(SELECT/, sql)
    end
  end

  test "count_sql limits each branch to COUNT_CEILING plus 1" do
    query = Fd::AuditQuery.new({}, actor: @me)

    assert_match(/LIMIT #{Fd::AuditQuery::COUNT_CEILING + 1}\)/, query.send(:count_sql))
  end
end

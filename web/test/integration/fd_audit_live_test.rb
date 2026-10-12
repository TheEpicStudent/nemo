require "test_helper"

class FdAuditLiveTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def query(term, view: "slack")
    Fd::AuditQuery.new({ "view" => view, "q" => term, "live" => "1" }, actor: @me)
  end

  test "watching critical events is pushed, watching everything is polled" do
    assert_equal({ "sources" => ["slack"], "actions" => ["anomaly"] }, query("did:anomaly").live_watch)
    assert_nil query("").live_watch
    assert_nil query("did:user_login").live_watch
    assert_nil query("category:sign_ins").live_watch
  end

  test "every action in the query has to be critical for it to be pushed" do
    assert query("did:anomaly did:cli_login").live_watch
    assert_nil query("did:anomaly did:user_login").live_watch
    assert query("did:pref.sign_in_with_slack_disabled").live_watch
  end

  test "watching one account, address, session or tor is pushed" do
    assert_equal({ "sources" => ["slack"], "actors" => ["UWATCHED"] }, query("actor:UWATCHED").live_watch)
    assert_equal({ "sources" => ["slack"], "subjects" => ["UWATCHED"] }, query("about:UWATCHED").live_watch)
    assert query("session:123").live_watch
    assert query("network:tor").live_watch
    assert_nil query("network:vpn").live_watch
  end

  test "identity reads and refusals are pushed" do
    assert_equal({ "sources" => ["read"] }, query("", view: "reads").live_watch)
    assert_equal({ "sources" => ["fire_engine"], "actions" => ["refused"] }, query("", view: "refusals").live_watch)
  end

  test "a pushed live page subscribes to the audit stream and carries what it watches" do
    get fd_audit_path(q: "did:anomaly", live: "1")

    assert_select "turbo-cable-stream-source"
    frame = css_select("turbo-frame#audit-results").first
    assert_equal({ "sources" => ["slack"], "actions" => ["anomaly"] }, JSON.parse(frame["data-audit-live-watch-value"]))
  end

  test "a page watching everything polls and does not subscribe" do
    get fd_audit_path(live: "1")

    assert_select "turbo-cable-stream-source", false
    assert_nil css_select("turbo-frame#audit-results").first["data-audit-live-watch-value"]
  end

  test "an audit event becomes a turbo stream action carrying the payload" do
    content = Fd::AuditLiveBroadcast.stream_tag('{"source":"slack","actions":["anomaly"],"actors":["U1"]}')

    assert_match(/<turbo-stream action="audit_event" payload="/, content)
    assert_includes CGI.unescapeHTML(content[/payload="([^"]*)"/, 1]), '"actions":["anomaly"]'
    assert_nil Fd::AuditLiveBroadcast.stream_tag("not json")
  end

  test "the listener relays audit events" do
    assert_includes Fd::ChatListener::CHANNELS, "fd_audit_event"
  end

  test "a committed slack audit row notifies fd_audit_event with its action, actor and subject" do
    listener = PG::Connection.new(PipelineConnection.connection.conninfo_hash.slice(:host, :port, :dbname, :user, :password))
    listener.exec("LISTEN fd_audit_event")
    id = SecureRandom.uuid
    as_pipeline(<<~SQL.squish, id)
      INSERT INTO slack.audit_event (id, at, action, category, actor_kind, actor_id, entity_kind, entity_id, ours, payload, source_key)
      VALUES (?::uuid, now(), 'anomaly', 'sign_ins', 'user', 'ULIVEACTOR', 'user', 'ULIVESUBJECT', false, '{}', 'test')
    SQL
    seeded!("slack.audit_event", "id", id)

    payload = nil
    listener.wait_for_notify(5) { |_channel, _pid, received| payload = JSON.parse(received) }

    assert_equal "slack", payload["source"]
    assert_equal ["anomaly"], payload["actions"]
    assert_equal ["ULIVEACTOR"], payload["actors"]
    assert_equal ["ULIVESUBJECT"], payload["subjects"]
  ensure
    listener&.close
  end
end

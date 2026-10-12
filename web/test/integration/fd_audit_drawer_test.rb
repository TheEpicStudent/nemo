require "test_helper"

class FdAuditDrawerTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  WHO = "UDRAWWHO".freeze
  AT = Time.utc(2026, 9, 29, 15, 37, 20)
  UA = "Mozilla/5.0 (Macintosh) Slack/4.41 drawer-test".freeze

  setup do
    hold_role!("UDRAWBOSS", "community_manager")
    @ff = hold_role!("UDRAWFF", "firefighter")
    sign_in_as(@ff)
    @ua = as_pipeline_value("INSERT INTO slack.user_agent (ua, app, os) VALUES (?, 'Slack desktop', 'macOS') " \
                            "ON CONFLICT (md5(ua)) DO UPDATE SET app = EXCLUDED.app RETURNING id", UA)
    as_pipeline("INSERT INTO fd.ip_network (ip_prefix, asn, network, country, class, source) " \
                "VALUES ('81.2.69.0/24', 64500, 'Example Net', 'GB', 'stable', 'ipinfo') ON CONFLICT DO NOTHING")
    seeded!("fd.ip_network", "ip_prefix", "81.2.69.0/24")
  end

  def as_pipeline_value(sql, *binds)
    as_pipeline(sql, *binds).first.values.first
  end

  def slack!(action: "user_login", at: AT, actor: WHO, payload: nil)
    id = SecureRandom.uuid
    payload ||= {
      id: id, action: action,
      actor: { type: "user", user: { id: actor, name: "Kid Realname", email: "kid@alts.example" } },
      entity: { type: "file", file: { id: "F0DRAW", name: "plans.pdf" } },
      context: { ip_address: "81.2.69.144", session_id: 4242, app: { id: "A0DRAWAPP", name: "Toolbox" } }
    }
    as_pipeline(<<~SQL.squish, id, at, action, actor, @ua, payload.to_json)
      INSERT INTO slack.audit_event (id, at, action, actor_kind, actor_id, entity_kind, entity_id, ours,
                                     ip, ua_id, app_id, session_id, payload, source_key)
      VALUES (?::uuid, ?, ?, 'user', ?, 'file', 'F0DRAW', false, '81.2.69.144'::inet, ?, 'A0DRAWAPP', 4242,
              ?::jsonb, 'test')
    SQL
    seeded!("slack.audit_event", "id", id)
    id
  end

  def fact(label)
    css_select(".side-facts dt").find { |term| term.text.squish == label }&.next_element&.text&.squish
  end

  test "the side pane lays the event out as fields, with the raw event folded" do
    id = slack!

    get fd_audit_event_path(source: "slack", id: id)
    assert_response :success
    assert_select ".side-kicker", text: "Slack · Sign-ins and security"
    assert_match "kid@alts.example", fact("Actor")
    assert_match "plans.pdf", fact("Target")
    assert_equal "81.2.69.144", fact("IP")
    assert_equal "Example Net · GB stable", fact("Network")
    assert_equal "Slack desktop · macOS", fact("Client")
    assert_equal "4242", fact("Session")
    assert_equal "Toolbox A0DRAWAPP", fact("App")
    assert_select "details.audit-panel-rawbox:not([open]) > summary", "Raw JSON"
    assert_select "details.audit-panel-rawbox pre", /Kid Realname/
  end

  test "without identity.read the email, address, location and real names stay out" do
    id = slack!
    move_capability!("firefighter", "identity.read", false, by: "UDRAWBOSS")

    get fd_audit_event_path(source: "slack", id: id)
    assert_equal "Hidden", fact("IP")
    assert_nil fact("Network")
    assert_no_match "kid@alts.example", response.body
    assert_no_match "Kid Realname", response.body
    assert_equal "Slack desktop · macOS", fact("Client")
    assert_match "plans.pdf", fact("Target")
  end

  test "related events are the same actor within 15 minutes, each opening in the drawer" do
    id = slack!
    related_id = slack!(action: "user_logout", at: AT + 5.minutes)
    slack!(action: "user_logout", at: AT + 40.minutes)
    slack!(actor: "UDRAWOTHER", at: AT + 1.minute)

    get fd_audit_event_path(source: "slack", id: id)
    links = css_select(".side-related a.side-related-row")
    assert_equal [fd_audit_event_path(source: "slack", id: related_id)], links.map { |one| one["href"] }
    assert_select ".side-related-all", count: 0
  end

  test "a busy quarter hour links to all of it" do
    id = slack!
    11.times { |n| slack!(at: AT + (n + 1).minutes) }

    get fd_audit_event_path(source: "slack", id: id)
    assert_select ".side-related a.side-related-row", 10
    assert_select ".side-related-all[href*='session'], .side-related-all[href*='after']", 1
  end

  test "an event with nothing extra still shows what it has" do
    id = slack!(payload: {})

    get fd_audit_event_path(source: "slack", id: id)
    assert_response :success
    assert_select ".side-kicker", text: "Slack · Sign-ins and security"
    assert_select "details.audit-panel-rawbox", count: 0
  end

  test "the audit page keeps an empty side pane beside the rows, and each row opens its event there" do
    id = slack!

    get fd_audit_path(q: "actor:#{WHO}")

    assert_select ".work.has-side > aside.side-pane > turbo-frame#audit-panel[data-controller=side-pane]"
    assert_select %(turbo-frame#audit-results[data-controller~="audit-rows"])
    assert_select %(tr.audit-row[data-event-url="#{fd_audit_event_path(source: "slack", id: id)}"][tabindex="0"])
  end

  test "an event named in the address opens in the side pane on load" do
    id = slack!

    get fd_audit_path(q: "actor:#{WHO}", event: "slack:#{id}")
    assert_select "turbo-frame#audit-panel[src=?]", fd_audit_event_path(source: "slack", id: id)

    get fd_audit_path(q: "actor:#{WHO}", event: "nowhere:#{id}")
    assert_select "turbo-frame#audit-panel:not([src])"
  end

  test "the network line counts the accounts seen on that address" do
    id = slack!
    %w[UDRAWIPONE UDRAWIPTWO].each do |user_id|
      as_pipeline(<<~SQL.squish, user_id)
        INSERT INTO fd.login_event (user_id, source, hour, ip, first_at, last_at)
        VALUES (?, 'audit_logs', date_trunc('hour', now()), '81.2.69.144'::inet, now(), now())
      SQL
      seeded!("fd.login_event", "user_id", user_id)
      seeded!("fd.member_trait", "user_id", user_id)
    end

    get fd_audit_event_path(source: "slack", id: id)

    assert_equal "Example Net · GB stable, 2 accounts on this IP", fact("Network")
  end

  test "the pane opens the member and their linked accounts" do
    member!(WHO)
    member!("UDRAWALT")
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal, signals) " \
                "VALUES (?, ?, 6.0, 'ip_exact', '{}'::jsonb)", *[WHO, "UDRAWALT"].sort)
    seeded!("fd.member_link", "a_user_id", [WHO, "UDRAWALT"].min)
    move_capability!("firefighter", "member.links", true, by: "UDRAWBOSS")
    id = slack!

    get fd_audit_event_path(source: "slack", id: id)

    assert_select %(.side-pivots a[href="#{fd_member_path(WHO)}"]), text: /Open member/
    assert_select %(.side-pivots a[href="#{fd_member_path(WHO, tab: "links")}"]), text: /1 linked account/
  end
end

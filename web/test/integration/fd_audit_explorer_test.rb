require "test_helper"

class FdAuditExplorerTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def slack!(actor: "UEXPONE", action: "user_login", ip: "81.2.69.144", at: 1.hour.ago)
    id = SecureRandom.uuid
    payload = { id: id, action: action, context: { ip_address: ip } }
    as_pipeline(<<~SQL.squish, id, at, action, actor, actor, ip, payload.to_json)
      INSERT INTO slack.audit_event (id, at, action, category, actor_kind, actor_id, entity_kind, entity_id,
                                     ours, ip, payload, source_key)
      VALUES (?::uuid, ?, ?, 'sign_ins', 'user', ?, 'user', ?, false, ?::inet, ?::jsonb, 'test')
    SQL
    seeded!("slack.audit_event", "id", id)
  end

  def network!(prefix, network_class, country)
    as_pipeline("INSERT INTO fd.ip_network (ip_prefix, class, country, source) VALUES (?::inet, ?, ?, 'curated') " \
                "ON CONFLICT (ip_prefix) DO UPDATE SET class = EXCLUDED.class, country = EXCLUDED.country",
      prefix, network_class, country)
    seeded!("fd.ip_network", "ip_prefix", prefix)
  end

  def query(term, view: "slack")
    Fd::AuditQuery.new({ "view" => view, "q" => term }, actor: @me)
  end

  test "AuditSearch.parse reads network and country qualifiers" do
    terms = Fd::AuditSearch.parse("network:VPN country:de net:nonsense").terms

    assert_equal [%w[network vpn], %w[country DE]], terms.map { |term| [term.kind, term.value] }
  end

  test "AuditSearch.parse maps by:me to the actor" do
    term = Fd::AuditSearch.parse("by:me", actor: @me).terms.first

    assert_equal ["actor", "UME"], [term.kind, term.value]
  end

  test "AuditQuery network and country qualifiers filter slack events by ip network" do
    network!("185.220.101.0/24", "tor", "DE")
    slack!(actor: "UEXPTOR", ip: "185.220.101.7")
    slack!(actor: "UEXPHOME", ip: "81.2.69.144")

    assert_equal %w[UEXPTOR], query("network:tor").rows.map(&:actor_id)
    assert_equal %w[UEXPTOR], query("country:de").rows.map(&:actor_id)
    assert_empty query("network:tor", view: "engine").rows
  end

  test "audit index with group country renders a country table" do
    network!("185.220.101.0/24", "tor", "DE")
    slack!(actor: "UEXPTOR", ip: "185.220.101.7")

    get fd_audit_path(group: "country")

    assert_select ".audit-groups th", "Country"
    assert_select ".audit-groups tbody td", text: "DE"
  end

  test "AuditQuery facet counts values ignoring its own filter" do
    network!("185.220.101.0/24", "tor", "DE")
    slack!(actor: "UEXPTOR", ip: "185.220.101.7")
    slack!(actor: "UEXPHOME", ip: "81.2.69.144", action: "user_logout")

    assert_equal 1, query("network:tor").facet("network")["tor"]
    assert_equal({ "user_login" => 1, "user_logout" => 1 }, query("action:user_login").facet("action").slice("user_login", "user_logout"))
    assert_equal 2, query("").facet("is")["human"].to_i + query("").facet("is")["nemo"].to_i
  end

  test "audit facet renders the counts in the facet turbo frame" do
    slack!

    get fd_audit_facet_path(facet: "action")

    assert_select "turbo-frame#audit-facet-action[target=_top]"
    assert_select "a.btn", text: /Signed in\s*1/
  end

  test "audit facet with an unknown facet returns 404" do
    get fd_audit_facet_path(facet: "nonsense")

    assert_response :not_found
  end

  test "audit index with add appends the term to q and redirects" do
    get fd_audit_path(q: "category:people", add: "last:7d")

    assert_redirected_to fd_audit_path(q: "category:people last:7d")
  end

  test "audit index renders one token per term with a remove link" do
    get fd_audit_path(q: "category:people last:7d")

    assert_select ".audit-qbar .audit-token", 2
    assert_select %(.audit-token a[href="#{fd_audit_path(q: "category:people")}"])
  end

  test "audit index query form sets the member url channel url and people values" do
    member!("UEXPONE", handle: "pixring")
    slack!

    get fd_audit_path

    form = css_select("form.audit-query").first
    assert_equal fd_member_search_path, form["data-audit-query-member-url-value"]
    assert_equal fd_channel_search_path, form["data-audit-query-channel-url-value"]
    assert_includes JSON.parse(form["data-audit-query-people-value"]), ["@pixring", "pixring"]
  end

  test "audit index shows the ip column when the payload has no ip with identity.read" do
    id = SecureRandom.uuid
    as_pipeline(<<~SQL.squish, id)
      INSERT INTO slack.audit_event (id, at, action, category, actor_kind, actor_id, ours, ip, payload, source_key)
      VALUES (?::uuid, now() - interval '1 hour', 'user_login', 'sign_ins', 'user', 'UEXPCOL', false,
              '81.2.69.150'::inet, '{}'::jsonb, 'test')
    SQL
    seeded!("slack.audit_event", "id", id)

    get fd_audit_path(q: "actor:UEXPCOL")

    assert_select "td.audit-ip", text: /81\.2\.69\.150/
  end

  test "audit index with live renders the live frame and keeps live in filter links" do
    get fd_audit_path(live: "1")

    assert_select %(a.btn[aria-pressed="true"][href="#{fd_audit_path}"]), text: /Live/
    assert_select %(turbo-frame#audit-results[data-controller~="audit-live"][data-audit-live-url-value="#{fd_audit_rows_path(live: "1")}"])
    assert_select %(.audit-filters a[href*="live=1"])

    get fd_audit_rows_path(live: "1")
    assert_select "turbo-frame#audit-results[target=_top]"
  end

  test "audit index with before_at renders no live controller" do
    get fd_audit_path(live: "1", before_at: 1.day.ago.iso8601, before_id: "x")

    assert_select %(turbo-frame#audit-results[data-controller~="audit-live"]), false
  end

  test "audit index lists the shared default saved queries" do
    get fd_audit_path

    assert_select ".audit-saved-pop a", text: /Sign-ins from Tor/
    assert_select ".audit-saved-pop a", text: /My actions/
  end

  test "saved query create stores the owner and only the owner sees and deletes it" do
    post fd_audit_saved_queries_path, params: { name: "Logins", query: "action:user_login", view: "" }
    saved = Fd::AuditSavedQuery.find_by!(name: "Logins")

    assert_redirected_to fd_audit_path(q: "action:user_login")
    assert_equal "UME", saved.owner_user_id
    assert Fd::AuditEntry.exists?(verb: "added", entity_type: "audit_query", entity_id: saved.id)

    sign_in_as(grant_role!("UOTHER", "community_manager"))
    get fd_audit_path
    assert_select ".audit-saved-pop a", text: /Logins/, count: 0
    delete fd_audit_saved_query_path(saved)
    assert Fd::AuditSavedQuery.exists?(saved.id)

    sign_in_as(@me)
    delete fd_audit_saved_query_path(saved)
    assert_not Fd::AuditSavedQuery.exists?(saved.id)
  ensure
    Fd::AuditSavedQuery.where(name: "Logins").delete_all
  end

  test "saved query with shared is listed for other users" do
    post fd_audit_saved_queries_path, params: { name: "Team logins", query: "action:user_login", shared: "1" }

    sign_in_as(grant_role!("UOTHER", "community_manager"))
    get fd_audit_path
    assert_select ".audit-saved-pop a", text: /Team logins/
  ensure
    Fd::AuditSavedQuery.where(name: "Team logins").delete_all
  end

  test "audit export returns csv rows and records an exported audit entry" do
    slack!(actor: "UEXPCSV")

    get fd_audit_export_path(q: "actor:UEXPCSV")

    lines = response.body.split("\r\n")
    assert_equal "text/csv", response.media_type
    assert_equal "time,source,actor,actor_kind,event,entity_kind,entity,target,ip,channel,session", lines.first
    assert_match(/slack,UEXPCSV,slack,user_login/, lines.second)
    entry = Fd::AuditEntry.where(verb: "exported", entity_type: "audit_query").order(:id).last
    assert_equal({ "q" => "actor:UEXPCSV", "view" => "slack", "rows" => 1 }, entry.after)
  end

  test "audit export omits ip without identity.read" do
    sign_in_as(grant_role!("UFFX", "firefighter"))
    override_capability!("firefighter", "identity.read", false, by: "UME")
    slack!(actor: "UEXPCSV", ip: "81.2.69.144")

    get fd_audit_export_path(q: "actor:UEXPCSV")

    assert_no_match(/81\.2\.69\.144/, response.body)
  end

  test "audit index shows the ip with identity.read" do
    slack!(actor: "UEXPIP", ip: "81.2.69.144")

    get fd_audit_path(q: "actor:UEXPIP")
    assert_select "td.audit-ip", text: /81\.2\.69\.144/
  end
end

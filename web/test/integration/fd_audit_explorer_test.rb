require "test_helper"

class FdAuditExplorerTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = hold_role!("UME", "community_manager")
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

  test "network and country read as qualifiers" do
    terms = Fd::AuditSearch.parse("network:VPN country:de net:nonsense").terms

    assert_equal [%w[network vpn], %w[country DE]], terms.map { |term| [term.kind, term.value] }
  end

  test "by:me is the person searching" do
    term = Fd::AuditSearch.parse("by:me", actor: @me).terms.first

    assert_equal ["actor", "UME"], [term.kind, term.value]
  end

  test "network and country filter slack events by the class of their address" do
    network!("185.220.101.0/24", "tor", "DE")
    slack!(actor: "UEXPTOR", ip: "185.220.101.7")
    slack!(actor: "UEXPHOME", ip: "81.2.69.144")

    assert_equal %w[UEXPTOR], query("network:tor").rows.map(&:actor_id)
    assert_equal %w[UEXPTOR], query("country:de").rows.map(&:actor_id)
    assert_empty query("network:tor", view: "engine").rows
  end

  test "events group by country" do
    network!("185.220.101.0/24", "tor", "DE")
    slack!(actor: "UEXPTOR", ip: "185.220.101.7")

    get fd_audit_path(group: "country")

    assert_select ".audit-groups th", "Country"
    assert_select ".audit-groups tbody td", text: "DE"
  end

  test "a facet counts its values without its own filter" do
    network!("185.220.101.0/24", "tor", "DE")
    slack!(actor: "UEXPTOR", ip: "185.220.101.7")
    slack!(actor: "UEXPHOME", ip: "81.2.69.144", action: "user_logout")

    assert_equal 1, query("network:tor").facet("network")["tor"]
    assert_equal({ "user_login" => 1, "user_logout" => 1 }, query("action:user_login").facet("action").slice("user_login", "user_logout"))
    assert_equal 2, query("").facet("is")["human"].to_i + query("").facet("is")["nemo"].to_i
  end

  test "a facet menu loads its counts into its own frame" do
    slack!

    get fd_audit_facet_path(facet: "action")

    assert_select "turbo-frame#audit-facet-action[target=_top]"
    assert_select "a.btn", text: /Signed in\s*1/
  end

  test "an unknown facet is not found" do
    get fd_audit_facet_path(facet: "nonsense")

    assert_response :not_found
  end

  test "typing a term into the bar adds it to the terms already there" do
    get fd_audit_path(q: "category:people", add: "last:7d")

    assert_redirected_to fd_audit_path(q: "category:people last:7d")
  end

  test "each term is a token with its own remove link" do
    get fd_audit_path(q: "category:people last:7d")

    assert_select ".audit-qbar .audit-token", 2
    assert_select %(.audit-token a[href="#{fd_audit_path(q: "category:people")}"])
  end

  test "the bar looks members and channels up and starts from the people on the page" do
    member!("UEXPONE", handle: "pixring")
    slack!

    get fd_audit_path

    form = css_select("form.audit-query").first
    assert_equal fd_member_search_path, form["data-audit-query-member-url-value"]
    assert_equal fd_channel_search_path, form["data-audit-query-channel-url-value"]
    assert_includes JSON.parse(form["data-audit-query-people-value"]), ["@pixring", "pixring"]
  end

  test "an address read from the event shows with identity.read" do
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

  test "live polls the newest rows and is kept across filters" do
    get fd_audit_path(live: "1")

    assert_select %(a.btn[aria-pressed="true"][href="#{fd_audit_path}"]), text: /Live/
    assert_select %(turbo-frame#audit-results[data-controller="audit-live"][data-audit-live-url-value="#{fd_audit_rows_path(live: "1")}"])
    assert_select %(.audit-filters a[href*="live=1"])

    get fd_audit_rows_path(live: "1")
    assert_select "turbo-frame#audit-results[target=_top]"
  end

  test "an older page does not poll" do
    get fd_audit_path(live: "1", before_at: 1.day.ago.iso8601, before_id: "x")

    assert_select %(turbo-frame#audit-results[data-controller="audit-live"]), false
  end

  test "the saved queries start with the shared defaults" do
    get fd_audit_path

    assert_select ".audit-saved-pop a", text: /Sign-ins from Tor/
    assert_select ".audit-saved-pop a", text: /My actions/
  end

  test "a query is saved for oneself, shown to its author and removable by them" do
    post fd_audit_saved_queries_path, params: { name: "Logins", query: "action:user_login", view: "" }
    saved = Fd::AuditSavedQuery.find_by!(name: "Logins")

    assert_redirected_to fd_audit_path(q: "action:user_login")
    assert_equal "UME", saved.owner_user_id
    assert Fd::AuditEntry.exists?(verb: "added", entity_type: "audit_query", entity_id: saved.id)

    sign_in_as(hold_role!("UOTHER", "community_manager"))
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

  test "a shared query is listed for everyone" do
    post fd_audit_saved_queries_path, params: { name: "Team logins", query: "action:user_login", shared: "1" }

    sign_in_as(hold_role!("UOTHER", "community_manager"))
    get fd_audit_path
    assert_select ".audit-saved-pop a", text: /Team logins/
  ensure
    Fd::AuditSavedQuery.where(name: "Team logins").delete_all
  end

  test "the export is csv of the search and is itself recorded" do
    slack!(actor: "UEXPCSV")

    get fd_audit_export_path(q: "actor:UEXPCSV")

    lines = response.body.split("\r\n")
    assert_equal "text/csv", response.media_type
    assert_equal "time,source,actor,actor_kind,event,entity_kind,entity,target,ip,channel,session", lines.first
    assert_match(/slack,UEXPCSV,slack,user_login/, lines.second)
    entry = Fd::AuditEntry.where(verb: "exported", entity_type: "audit_query").order(:id).last
    assert_equal({ "q" => "actor:UEXPCSV", "view" => "slack", "rows" => 1 }, entry.after)
  end

  test "an export leaves addresses out without identity.read" do
    sign_in_as(hold_role!("UFFX", "firefighter"))
    move_capability!("firefighter", "identity.read", false, by: "UME")
    slack!(actor: "UEXPCSV", ip: "81.2.69.144")

    get fd_audit_export_path(q: "actor:UEXPCSV")

    assert_no_match(/81\.2\.69\.144/, response.body)
  end

  test "an address shows only with identity.read" do
    slack!(actor: "UEXPIP", ip: "81.2.69.144")

    get fd_audit_path(q: "actor:UEXPIP")
    assert_select "td.audit-ip", text: /81\.2\.69\.144/
  end
end

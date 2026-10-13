require "test_helper"

class FdClustersTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  ROOT = "UCROOT".freeze
  ALT = "UCALT".freeze
  DELETED = "UCGONE".freeze

  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    [ROOT, ALT, DELETED].each_with_index do |user_id, at|
      member!(user_id)
      cluster!(user_id, ROOT, active: user_id != DELETED)
      joined!(user_id, (3 - at).days.ago)
    end
    as_pipeline("UPDATE fd.member SET is_deleted = true WHERE user_id = ?", DELETED)
    link!(ROOT, ALT, 9.5)
    link!(ALT, DELETED, 6.0)
    login_event!(ROOT, "81.2.69.144", 2.days.ago)
    login_event!(ALT, "81.2.69.144", 2.days.ago)
    login_event!(DELETED, "10.9.9.9", 1.day.ago)
    snapshot!(DELETED)
  end

  test "a cluster page draws every account and the links between them" do
    get fd_cluster_path(ROOT)
    assert_response :success

    assert_select ".cluster-map a.node", 3
    assert_select ".cluster-map path.edge-certain[data-a=?][data-b=?]", ALT, ROOT
    assert_select ".cluster-map path.edge-strong", 1
    assert_select ".cluster-map svg.is-crowded", count: 0
    assert_select ".cluster-map a.node[data-user=?]", ROOT
    assert_select ".cluster-map a.node-gone", 1

    get fd_cluster_path(ROOT, tab: "accounts")
    assert_select "table.data-table tbody tr", 3
  end

  test "accounts with no link between them share one ring and keep their names" do
    20.times do |n|
      user_id = "UCBIG#{n.to_s.rjust(2, '0')}"
      member!(user_id)
      cluster!(user_id, ROOT, active: true)
    end

    get fd_cluster_path(ROOT)
    svg = css_select(".cluster-map svg").first
    assert_not_includes svg["class"], "is-packed"
    assert_select ".cluster-map a.node", 23
    assert_select ".cluster-map .node-name", 23
    assert_select ".cluster-map .node-name[transform]", count: 0
    assert_select ".cluster-map circle.face-ring[r='18']", 23
  end

  test "a cluster past twenty four shrinks its faces and names only the hub of each group" do
    70.times do |n|
      user_id = "UCDISC#{n.to_s.rjust(2, '0')}"
      member!(user_id)
      cluster!(user_id, ROOT, active: n.odd?)
    end

    get fd_cluster_path(ROOT)
    svg = css_select(".cluster-map svg").first
    assert_includes svg["class"], "is-packed"
    assert_select ".cluster-map a.node", 73
    assert_select ".cluster-map a.node image", 73
    assert_select ".cluster-map circle.face-ring[r='11']", 73
    assert_equal [ALT], css_select(".cluster-map .node-name").map { |name| name.parent["data-user"] }
    assert_select ".cluster-map text.map-hover[data-cluster-map-target=label]", 1
    assert_select ".cluster-map a.node[data-name][data-x][data-y]", 73
  end

  test "every account on the map shows its face and opens beside the map" do
    get fd_cluster_path(ROOT)

    [ROOT, ALT, DELETED].each do |user_id|
      assert_select ".cluster-map a.node[href='#{node_fd_cluster_path(ROOT, user_id)}'][data-turbo-frame='cluster-node']" do
        assert_select "image[href$='/#{user_id}/r']"
        assert_select "text.node-name"
      end
    end
  end

  test "the sessions show which address the accounts shared" do
    get fd_cluster_path(ROOT, tab: "sessions")

    assert_select ".cluster-cells i.shared", 2
    assert_select ".cluster-cells i.own", 1
    assert_match "81.2.69.144", response.body
    legend = css_select(".cluster-map-key").map(&:text).join
    assert_includes legend, "81.2.69.144"
    assert_not_includes legend, "10.9.9.9", "an address one account used alone is not listed as shared"
  end

  test "the evidence frozen at deactivation is shown" do
    get fd_cluster_path(ROOT, tab: "snapshots")

    assert_equal %w[Account Deactivated By Reason Email IPs Clients], css_select("thead th").map { |cell| cell.text.squish }
    assert_match "ban evasion", response.body
    assert_select "tbody td div.mono", "10.9.9.9"
  end

  test "reading a cluster is logged for every account in it" do
    assert_difference -> { AccessLog.where(field_class: "links", subject_user_id: [ROOT, ALT, DELETED]).count }, 3 do
      get fd_cluster_path(ROOT)
    end
    assert_equal 3, AccessLog.where(field_class: "login", subject_user_id: [ROOT, ALT, DELETED]).count
  end

  test "without identity.read the addresses and snapshots stay hidden" do
    move_capability!("firefighter", "identity.read", false, by: "UME")
    sign_in_as(hold_role!("UFF", "firefighter"))

    get fd_cluster_path(ROOT)
    assert_response :success
    assert_select "nav.views a.view", text: /Sessions|Snapshots/, count: 0
    assert_no_match "81.2.69.144", response.body

    get fd_cluster_path(ROOT, tab: "sessions")
    assert_select "h2", text: "Sign-ins per day", count: 0
  end

  test "a case can be opened about the whole cluster" do
    get fd_cluster_path(ROOT)

    href = css_select("a.btn-primary").find { |one| one.text.include?("Open case") }["href"]
    [ROOT, ALT, DELETED].each { |user_id| assert_includes CGI.unescape(href), "subject_user_ids[]=#{user_id}" }
  end

  test "deactivating from a cluster opens a guard per active account and comes back here" do
    get fd_cluster_path(ROOT)
    assert_select ".modal-host[data-modal-id-value='cluster-deactivate'] input[name='user_ids[]']", 2

    assert_difference -> { Fd::MemberGuard.where(kind: "deactivation").count }, 2 do
      post fd_bulk_deactivations_path, params: { user_ids: [ROOT, ALT], reason: "ring", cluster_id: ROOT }
    end
    assert_redirected_to fd_cluster_path(ROOT)
  end

  test "an unknown cluster is not found" do
    get fd_cluster_path("UNOBODY")
    assert_response :not_found
  end

  test "the clusters tab and a member pane both lead to the cluster" do
    get fd_clusters_path
    assert_select "a.ccard-link[href='#{fd_cluster_path(ROOT)}']"

    get fd_member_links_path(ALT)
    assert_select "a[href='#{fd_cluster_path(ROOT)}']", "Open cluster"
  end

  private

  def cluster!(user_id, cluster_id, active:)
    as_pipeline("INSERT INTO fd.member_cluster (user_id, cluster_id, accounts, ring, active) VALUES (?, ?, 3, false, ?)",
      user_id, cluster_id, active)
    seeded!("fd.member_cluster", "user_id", user_id)
  end

  def joined!(user_id, at)
    as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) VALUES (?, ?, 'team_join') " \
                "ON CONFLICT (user_id) DO NOTHING", user_id, at)
    seeded!("fd.member_joins", "user_id", user_id)
  end

  def link!(one, two, score)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal) VALUES (?, ?, ?, 'ip_stable')",
      a, b, score)
    seeded!("fd.member_link", "a_user_id", a)
  end

  def login_event!(user_id, ip, at)
    as_pipeline(<<~SQL.squish, user_id, at, ip, at, at)
      INSERT INTO fd.login_event (user_id, source, hour, ip, first_at, last_at)
      VALUES (?, 'audit_logs', date_trunc('hour', ?::timestamptz, 'UTC'), ?::inet, ?, ?)
    SQL
    seeded!("fd.login_event", "user_id", user_id)
    seeded!("fd.member_trait", "user_id", user_id)
    seeded!("fd.member_touch", "user_id", user_id)
  end

  def snapshot!(user_id)
    as_pipeline(<<~SQL.squish, user_id)
      INSERT INTO fd.evidence_snapshot (user_id, deactivated_at, source, actor_id, reason, identity, traits, links)
      VALUES (?, now() - interval '1 day', 'fire_engine', 'UME', 'ban evasion', '{}',
              '[{"kind": "ip", "value": "10.9.9.9"}]', '[{"other": "UCALT", "score": 6.0}]')
    SQL
    seeded!("fd.evidence_snapshot", "user_id", user_id)
  end
end

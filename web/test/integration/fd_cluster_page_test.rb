require "test_helper"

class FdClusterPageTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  ROOT = "UPGA".freeze

  setup do
    @me = hold_role!("UPGBOSS", "community_manager")
    sign_in_as(@me)
    %w[UPGA UPGB UPGC UPGD].each_with_index do |user_id, index|
      member!(user_id)
      as_pipeline("INSERT INTO fd.member_cluster (user_id, cluster_id, accounts, ring, active, conflict) VALUES (?, ?, 4, false, true, true)",
        user_id, ROOT)
      seeded!("fd.member_cluster", "user_id", user_id)
      as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) VALUES (?, ?, 'team_join')", user_id, (10 - index).days.ago)
      seeded!("fd.member_joins", "user_id", user_id)
    end
    link!("UPGA", "UPGB", 9.0)
    link!("UPGB", "UPGC", 6.0)
    link!("UPGC", "UPGD", 9.5)
    verdict!("UPGA", "UPGD", "different_people")
  end

  SIGNALS = '{"ip_stable": {"value": "81.2.69.144", "people": 4, "score": 5.0}}'.freeze

  def link!(one, two, score)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal, signals) " \
                "VALUES (?, ?, ?, 'ip_stable', ?::jsonb)", a, b, score, SIGNALS)
    seeded!("fd.member_link", "a_user_id", a)
  end

  def verdict!(one, two, verdict)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link_verdict (a_user_id, b_user_id, verdict, decided_by) VALUES (?, ?, ?, 'UPGBOSS')",
      a, b, verdict)
    seeded!("fd.member_link_verdict", "a_user_id", a)
  end

  test "the page opens on the overview with its tabs counted" do
    get fd_cluster_path(ROOT)
    assert_response :success

    tabs = css_select("nav.views a.view").map { |tab| tab.text.squish }
    assert_equal ["Overview", "Accounts 4", "Links 3", "Sessions", "Snapshots 0", "Verdicts 1"], tabs
    assert_select ".cluster-stat dd", "4"
    assert_select ".cluster-map svg"
    assert_select ".px-maptools input[type=range][max='4'][data-action='input->cluster-map#scrub']"
    assert_select "details.foldcard.cluster-timeline-fold:not([open]) > summary", "Timeline"
    assert_select ".cluster-timeline svg circle.timeline-dot", 4
  end

  test "values shared across the cluster are listed with who shares them" do
    get fd_cluster_path(ROOT)

    row = css_select(".card table.data-table tbody tr").first
    assert_match "81.2.69.144", row.text
    assert_equal 4, row.css(".facepile-face").size
  end

  test "a verdict conflict offers to split on the weakest link between the two" do
    get fd_cluster_path(ROOT)
    assert_select ".rv-alert.crit .rv-alert-title", "Verdict conflict"
    assert_select "button[data-modal-open=cluster-split]"
    assert_select ".modal-host[data-modal-id-value='cluster-split'] .split-cut", 1

    assert_difference -> { Fd::LinkVerdict.where(verdict: "different_people").count }, 1 do
      post fd_cluster_split_path(ROOT)
    end
    assert_redirected_to fd_cluster_path(ROOT)
    assert_equal "1 link marked different people", flash[:notice]
    cut = Fd::LinkVerdict.find_by!(a_user_id: "UPGB", b_user_id: "UPGC")
    assert_equal ["different_people", "UPGBOSS", "Split cluster UPGA"], [cut.verdict, cut.decided_by, cut.note]
  end

  test "a same person verdict is never cut, so the next weakest link goes" do
    verdict!("UPGB", "UPGC", "same_person")

    split = Fd::ClusterSplit.new(Fd::ClusterView.find(ROOT))
    assert_equal [%w[UPGA UPGB]], split.cuts.map { |cut| [cut.a_user_id, cut.b_user_id] }
  end

  test "pairs held together only by same person verdicts cannot be split" do
    verdict!("UPGA", "UPGB", "same_person")
    verdict!("UPGB", "UPGC", "same_person")
    verdict!("UPGC", "UPGD", "staff_test")

    assert_not Fd::ClusterSplit.new(Fd::ClusterView.find(ROOT)).possible?
  end

  test "nothing to split without a conflict" do
    as_pipeline("DELETE FROM fd.member_link_verdict WHERE a_user_id = 'UPGA' AND b_user_id = 'UPGD'")
    post fd_cluster_split_path(ROOT)
    assert_equal "nothing to split", flash[:alert]
  end

  test "an account opens in the side pane with its links and ways out" do
    get node_fd_cluster_path(ROOT, "UPGB"), headers: { "Turbo-Frame" => "cluster-node" }
    assert_response :success

    assert_select "turbo-frame#cluster-node .side-title"
    assert_select ".side-related a.side-related-row", 2
    assert_select ".side-related a[href=?]", fd_link_compare_path(a: "UPGB", b: "UPGA", back: fd_cluster_path(ROOT))
    assert_select ".side-pivots a[href=?]", fd_audit_path(q: "about:UPGB")
    get fd_cluster_path(ROOT)
    assert_select "aside.side-pane > turbo-frame#cluster-node[data-controller=side-pane]"
  end

  test "an account opened outside the pane lands on the cluster with its pane open" do
    get node_fd_cluster_path(ROOT, "upgb")
    assert_redirected_to fd_cluster_path(ROOT, node: "UPGB")

    follow_redirect!
    assert_select "aside.side-pane > turbo-frame#cluster-node[src=?]", node_fd_cluster_path(ROOT, "UPGB")
    get fd_cluster_path(ROOT, node: "UNOTHERE")
    assert_select "aside.side-pane > turbo-frame#cluster-node:not([src])"
  end

  test "the verdicts tab lists who decided what" do
    get fd_cluster_path(ROOT, tab: "verdicts")

    assert_select "tbody tr", 1
    assert_select "tbody .state", "Different people"
  end

  test "the accounts tab compares each account with the oldest" do
    get fd_cluster_path(ROOT, tab: "accounts")

    assert_select "tbody tr", 4
    assert_select "a.btn[href=?]", fd_link_compare_path(a: ROOT, b: "UPGD", back: fd_cluster_path(ROOT, tab: "accounts"))
  end
end

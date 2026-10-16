require "test_helper"

class FdMemberLinksTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  test "links index returns success" do
    get fd_links_path
    assert_response :success
  end

  test "links index renders a cable stream source and the list turbo frame with data-src" do
    get fd_links_path(view: "strong")

    assert_select "turbo-cable-stream-source"
    assert_select %(turbo-frame##{Fd::MemberLinkBroadcast::LIST_FRAME}[data-src="#{fd_links_path(view: "strong")}"])
  end

  test "member links tab renders cable stream sources and the member links frame" do
    member!("UONE")
    get fd_member_path("UONE", tab: "links")

    assert_select "turbo-cable-stream-source", minimum: 2
    assert_select %(turbo-frame#member-links-UONE)
  end

  test "member links pane lists the linked account and for_member returns band certain" do
    member!("UONE")
    member!("UTWO")
    link!("UONE", "UTWO", score: 9.5, top: "ip_exact",
      signals: '{"ip_exact": {"value": "1.2.3.4", "people": 2, "score": 5.0}}')

    get fd_member_links_path("UONE")
    assert_response :success
    assert_match "UTWO", response.body

    links = Fd::MemberLink.for_member("UONE")
    assert_equal 1, links.size
    assert_equal "UTWO", links.first.other_id
    assert links.first.certain?
    assert_equal "certain", links.first.band
  end

  test "for_member finds a link from either member" do
    member!("UONE")
    member!("UTWO")
    link!("UONE", "UTWO", score: 3.0, top: "ip_prefix")

    assert_equal ["UTWO"], Fd::MemberLink.for_member("UONE").map(&:other_id)
    assert_equal ["UONE"], Fd::MemberLink.for_member("UTWO").map(&:other_id)
  end

  test "band is weak for score 3.0" do
    member!("UONE")
    member!("UTWO")
    link!("UONE", "UTWO", score: 3.0, top: "ip_prefix")

    assert_equal "weak", Fd::MemberLink.for_member("UONE").first.band
  end

  test "links index without member.links redirects" do
    override_capability!("firefighter", "member.links", false, by: "UME")
    sign_in_as(grant_role!("UFF", "firefighter"))

    get fd_links_path
    assert_response :redirect
  end

  test "links index defaults to the unreviewed view with strong links to deleted accounts" do
    member!("UACTIVE")
    member!("UGONE")
    member!("UJUDGED")
    member!("UWEAK")
    member!("UBOTHON")
    mark_deleted!("UGONE")
    mark_deleted!("UJUDGED")
    mark_deleted!("UWEAK")
    link!("UACTIVE", "UGONE", score: 9.5, top: "mailbox_alias",
      signals: '{"mailbox_alias": {"value": "kid@gmail.com", "people": 2, "score": 8.0}}')
    link!("UACTIVE", "UJUDGED", score: 9.0, top: "ip_stable")
    link!("UACTIVE", "UWEAK", score: 3.5, top: "ip_prefix_stable")
    link!("UACTIVE", "UBOTHON", score: 9.0, top: "ip_stable")
    verdict!("UACTIVE", "UJUDGED", "different_people")

    get fd_links_path
    assert_response :success

    assert_select ".view[aria-current=true]", /Unreviewed/
    rows = css_select("tbody tr")
    assert_equal 1, rows.size
    assert_match(/ugone/i, rows.first.text)
    assert_match "Same normalized mailbox", rows.first.text
    assert_match "kid@gmail.com", rows.first.text
  end

  test "links index with view clusters redirects to clusters and view pairs to strong" do
    get fd_links_path(view: "clusters")
    assert_redirected_to fd_clusters_path

    get fd_links_path(view: "pairs", over: "strong")
    assert_redirected_to fd_links_path(view: "strong")
  end

  test "links index certain view lists only certain links with the signal value" do
    member!("UONE")
    member!("UTWO")
    member!("UTHREE")
    link!("UONE", "UTWO", score: 9.5, top: "ip_stable",
      signals: '{"ip_stable": {"value": "81.2.69.144", "people": 2, "score": 5.0}}')
    link!("UONE", "UTHREE", score: 3.5, top: "ip_prefix_stable")

    get fd_links_path(view: "certain")
    assert_response :success

    assert_select ".view[aria-current=true]", /Certain/
    assert_equal 1, css_select("tbody tr").size
    assert_match "81.2.69.144", response.body
  end

  test "member links pane lists other cluster accounts when the member has no direct links" do
    member!("UONE")
    cluster!("UONE", "UROOT", accounts: 3, active: true)
    cluster!("UROOT", "UROOT", accounts: 3, active: true)
    cluster!("UTHIRD", "UROOT", accounts: 3, active: false)

    get fd_member_links_path("UONE")
    assert_response :success

    assert_select ".link-mates-title", "Cluster"
    assert_select ".link-mates-head", /2 other accounts, 1 deactivated/
    assert_select ".facepile a.facepile-face.is-gone[title*=deactivated]", 1
    assert_select ".link-mates-open", 1
    assert_match "UROOT", response.body
    assert_match "UTHIRD", response.body
    assert_select ".empty-title", count: 0
  end

  test "member links pane limits cluster faces to CLUSTER_MEMBER_LIMIT and shows a more count" do
    member!("UONE")
    cluster!("UONE", "UBIG00", accounts: 21, active: true)
    20.times { |n| cluster!("UBIG#{n.to_s.rjust(2, '0')}", "UBIG00", accounts: 21, active: true) }

    get fd_member_links_path("UONE")
    assert_select ".facepile a.facepile-face", Fd::MemberLink::CLUSTER_MEMBER_LIMIT
    assert_select ".facepile .facepile-more", "+4"
    assert_select ".link-mates-head", /20 other accounts/
    assert_select "a", text: "Open cluster", count: 1
  end

  test "links index certain view renders no facts strip and no rescoring queue text" do
    get fd_links_path(view: "certain")

    assert_select "dl.facts-strip", 0
    assert_no_match "Queued for rescoring", response.body
  end

  test "lane_run_label returns n/a for a run that never ran" do
    health = Fd::LinkHealth.new(queued: 0, oldest_touched_at: nil, runs: {})

    assert health.run("member_links").never?
    assert_not health.run("member_links").running?
    assert_equal "n/a", ApplicationController.helpers.lane_run_label(health.run("member_links"))
  end

  test "sidebar renders the Alts and Records groups and marks the current page" do
    get fd_clusters_path

    assert_select "p.community-nav-label", text: "Alts"
    assert_select "p.community-nav-label", text: "Records"
    assert_select %(a[href="#{fd_links_path}"]), text: /Review/
    assert_select %(a[href="#{fd_links_path(view: "certain")}"]), text: /Links/
    assert_select %(a[aria-current="page"][href="#{fd_clusters_path}"]), text: /Clusters/

    get fd_links_path(view: "weak")
    assert_select %(a[aria-current="page"][href="#{fd_links_path(view: "certain")}"]), text: /Links/
  end

  private

  def mark_deleted!(user_id)
    as_pipeline("UPDATE fd.member SET is_deleted = true WHERE user_id = ?", user_id)
  end

  def verdict!(one, two, verdict)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link_verdict (a_user_id, b_user_id, verdict, decided_by) " \
                "VALUES (?, ?, ?, 'UME')", a, b, verdict)
    seeded!("fd.member_link_verdict", "a_user_id", a)
  end

  def cluster!(user_id, cluster_id, accounts:, active:, ring: false, conflict: false)
    as_pipeline("INSERT INTO fd.member_cluster (user_id, cluster_id, accounts, ring, active, conflict) " \
                "VALUES (?, ?, ?, ?, ?, ?)", user_id, cluster_id, accounts, ring, active, conflict)
    seeded!("fd.member_cluster", "user_id", user_id)
  end

  def link!(one, two, score:, top:, signals: "{}")
    a, b = [one, two].sort
    as_pipeline(<<~SQL.squish, a, b, score, top, signals)
      INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal, signals)
      VALUES (?, ?, ?, ?, ?::jsonb)
    SQL
    seeded!("fd.member_link", "a_user_id", a)
  end

  test "MEMBER_LINK_LIMIT is 25 and BANDS has no most_per_member" do
    assert_equal 25, Fd::MemberLink::MEMBER_LINK_LIMIT
    assert_not Fd::MemberLink::BANDS.key?("most_per_member")
  end
end

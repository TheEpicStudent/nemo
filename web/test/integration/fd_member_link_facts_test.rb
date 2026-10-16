require "test_helper"

class FdMemberLinkFactsTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  WHO = "UFACTS1".freeze

  setup do
    sign_in_as(grant_role!("UME", "community_manager"))
    member!(WHO)
  end

  def link!(other, score)
    a, b = [WHO, other].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal) VALUES (?, ?, ?, 'ip_stable')",
      a, b, score)
    seeded!("fd.member_link", "a_user_id", a)
  end

  def fact(label)
    css_select(".member-facts .fact").find { |one| one.at("dt").text.strip == label }
  end

  test "member page Links fact shows the link count and certain count with a links tab link" do
    link!("UFACTS2", 9.0)
    link!("UFACTS3", 6.0)
    link!("UFACTS4", 3.5)

    get fd_member_path(WHO)
    assert_response :success

    links = fact("Links")
    assert_match(/3\s+1 certain/, links.text.squish)
    assert links.at("a.fact-go[href='#{fd_member_path(WHO, tab: "links")}']")
  end

  test "member page Cluster fact links to the cluster page and shows account count and Ring" do
    as_pipeline("INSERT INTO fd.member_cluster (user_id, cluster_id, accounts, ring, active, conflict) " \
                "VALUES (?, 'UFACTSROOT', 5, true, true, false)", WHO)
    seeded!("fd.member_cluster", "user_id", WHO)

    get fd_member_path(WHO)

    cluster = fact("Cluster")
    assert_equal fd_cluster_path("UFACTSROOT"), cluster.at("a")["href"]
    assert_match "5 accounts", cluster.text
    assert_match "Ring", cluster.text
  end

  test "member page shows None for Links and Cluster facts without rows" do
    get fd_member_path(WHO)

    assert_equal "None", fact("Links").at("dd").text.strip
    assert_equal "None", fact("Cluster").at("dd").text.strip
  end

  test "member page without member.links renders neither Links nor Cluster fact" do
    override_capability!("firefighter", "member.links", false, by: "UME")
    sign_in_as(grant_role!("UFF", "firefighter"))

    get fd_member_path(WHO)
    assert_response :success
    assert_nil fact("Links")
    assert_nil fact("Cluster")
    assert_select ".member-facts.has-links", 0
  end
end

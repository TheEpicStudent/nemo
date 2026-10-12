require "test_helper"

class FdClusterCardsTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    sign_in_as(hold_role!("UCARDBOSS", "community_manager"))
    cluster!(%w[UCARDR1 UCARDR2 UCARDR3 UCARDR4], ring: true)
    cluster!(%w[UCARDE1 UCARDE2], gone: %w[UCARDE1])
    snapshot!("UCARDE1", 10.days.ago)
    joined!("UCARDE1", 30.days.ago)
    joined!("UCARDE2", 3.days.ago)
    cluster!(%w[UCARDC1 UCARDC2 UCARDC3], conflict: true)
    link!("UCARDR1", "UCARDR2", 9.0)
    link!("UCARDR2", "UCARDR3", 6.0)
  end

  def cluster!(user_ids, ring: false, conflict: false, gone: [])
    user_ids.each do |user_id|
      member!(user_id)
      as_pipeline("UPDATE fd.member SET is_deleted = true WHERE user_id = ?", user_id) if gone.include?(user_id)
      as_pipeline("INSERT INTO fd.member_cluster (user_id, cluster_id, accounts, ring, active, conflict) VALUES (?, ?, ?, ?, ?, ?)",
        user_id, user_ids.first, user_ids.size, ring, !gone.include?(user_id), conflict)
      seeded!("fd.member_cluster", "user_id", user_id)
    end
  end

  def joined!(user_id, at)
    as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) VALUES (?, ?, 'team_join')", user_id, at)
    seeded!("fd.member_joins", "user_id", user_id)
  end

  def snapshot!(user_id, at)
    as_pipeline("INSERT INTO fd.evidence_snapshot (user_id, deactivated_at, source, identity, traits, links) " \
                "VALUES (?, ?, 'fire_engine', '{}', '[]', '[]')", user_id, at)
    seeded!("fd.evidence_snapshot", "user_id", user_id)
  end

  def link!(one, two, score)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal) VALUES (?, ?, ?, 'ip_stable')", a, b, score)
    seeded!("fd.member_link", "a_user_id", a)
  end

  def card(cluster_id)
    css_select("article.ccard").find { |one| one.at_css("a.ccard-link")["href"] == fd_cluster_path(cluster_id) }
  end

  test "every cluster is a card with its graph and counts" do
    get fd_clusters_path
    assert_response :success

    ring = card("UCARDR1")
    assert_equal 4, ring.css("svg.ccard-map circle.mini-node").size
    assert_equal 1, ring.css("svg.ccard-map path.edge-certain").size
    assert_equal 1, ring.css("svg.ccard-map path.edge-strong").size
    assert_match("4 active", ring.text.squish)
    assert_match "Ring", ring.text
    assert_match "Top signal: Signed in from the same home or office address", ring.text
  end

  test "a join after a ban in the same cluster is evasion" do
    get fd_clusters_path(filter: "evasion")

    assert_equal [fd_cluster_path("UCARDE1")], css_select("a.ccard-link").map { |link| link["href"] }
    assert_match "1 post-ban join", card("UCARDE1").text
    assert_equal 1, card("UCARDE1").css("circle.mini-node.is-gone").size
  end

  test "rings and conflicts filter the cards" do
    get fd_clusters_path(filter: "ring")
    assert_equal [fd_cluster_path("UCARDR1")], css_select("a.ccard-link").map { |link| link["href"] }

    get fd_clusters_path(filter: "conflict")
    assert_equal [fd_cluster_path("UCARDC1")], css_select("a.ccard-link").map { |link| link["href"] }
    assert_match "Verdict conflict", card("UCARDC1").text
    assert_select ".segmented a[aria-current=true]", "Conflicts"
  end

  test "the clusters page needs member.links" do
    move_capability!("firefighter", "member.links", false, by: "UCARDBOSS")
    sign_in_as(hold_role!("UCARDFF", "firefighter"))

    get fd_clusters_path
    assert_response :redirect
  end
end

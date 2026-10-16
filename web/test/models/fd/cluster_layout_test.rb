require "test_helper"

class Fd::ClusterLayoutTest < ActiveSupport::TestCase
  Member = Struct.new(:user_id, keyword_init: true)
  Edge = Struct.new(:a_user_id, :b_user_id, :score, :verdict, keyword_init: true) do
    def apart? = verdict == "different_people"
  end
  Cluster = Struct.new(:members, :edges, keyword_init: true)

  def cluster(ids, links, verdicts = [])
    edges = links.map { |a, b, score| Edge.new(a_user_id: a, b_user_id: b, score: score) } +
            verdicts.map { |a, b, verdict| Edge.new(a_user_id: a, b_user_id: b, score: nil, verdict: verdict) }
    Cluster.new(members: ids.map { |id| Member.new(user_id: id) }, edges: edges)
  end

  def star(prefix, count, score = 8.0)
    ids = (1..count).map { |n| "#{prefix}#{n}" }
    [ids, ids.drop(1).map { |id| [ids.first, id, score] }]
  end

  test "pair layout has pair size and two labeled points on one row" do
    layout = Fd::ClusterLayout.new(cluster(%w[A B], [["A", "B", 9.0]]))

    assert_equal [Fd::ClusterLayout::PAIR_WIDTH, Fd::ClusterLayout::PAIR_HEIGHT], [layout.width, layout.height]
    assert_equal layout.points["A"].y, layout.points["B"].y
    assert_operator layout.points["A"].x, :<, layout.points["B"].x
    assert layout.points.values.all?(&:labeled)
  end

  test "star group hub is at group center with L spoke paths and Q side-link paths" do
    ids, links = star("S", 6)
    links << ["S2", "S3", 5.5]
    layout = Fd::ClusterLayout.new(cluster(ids, links))

    assert_equal 1, layout.groups.size
    assert_equal "S1", layout.groups.first.hub
    hub = layout.points["S1"]
    assert_equal [layout.groups.first.x, layout.groups.first.y], [hub.x, hub.y]
    assert_match(/\AM[\d. ]+ L/, layout.edge_path("S1", "S4"))
    assert_match(/\AM[\d. ]+ Q/, layout.edge_path("S2", "S3"))
  end

  test "hub is the account with the most links" do
    ids = %w[A B C D E]
    links = [["B", "A", 8.0], ["B", "C", 8.0], ["B", "D", 8.0], ["B", "E", 8.0]]

    assert_equal "B", Fd::ClusterLayout.new(cluster(ids, links)).groups.first.hub
  end

  test "two stars joined by one link form two groups on one row with an L bridge path" do
    first_ids, first_links = star("P", 6)
    second_ids, second_links = star("Q", 6)
    layout = Fd::ClusterLayout.new(cluster(first_ids + second_ids, first_links + second_links + [["P6", "Q2", 5.4]]))

    assert_equal 2, layout.groups.size
    assert_equal %w[P1 Q1], layout.groups.map(&:hub).sort
    assert_in_delta layout.groups.first.y, layout.groups.last.y, 0.1
    assert_match(/\AM[\d. ]+ L/, layout.edge_path("P6", "Q2"))
    assert_not_equal layout.points["P6"].group, layout.points["Q2"].group
  end

  test "different_people verdict edge leaves the star as one group with hub V1" do
    ids, links = star("V", 4)
    layout = Fd::ClusterLayout.new(cluster(ids, links, [["V1", "V2", "different_people"]]))

    assert_equal 1, layout.groups.size
    assert_equal "V1", layout.groups.first.hub
  end

  test "account with only a weak link is added to the neighbour group others" do
    ids, links = star("W", 5)
    ids << "LONE"
    links << ["W3", "LONE", 3.4]
    layout = Fd::ClusterLayout.new(cluster(ids, links))

    assert_equal 1, layout.groups.size
    assert_includes layout.groups.first.others, "LONE"
  end

  test "large clusters are packed with smaller node size and only hubs labeled" do
    ids, links = star("B", 40)
    layout = Fd::ClusterLayout.new(cluster(ids, links))

    assert layout.packed?
    assert_equal 14, layout.node
    assert_equal ["B1"], layout.points.select { |_id, point| point.labeled }.keys
    assert_equal 11, Fd::ClusterLayout.new(cluster(*star("H", 70))).node
  end

  test "all points are within canvas width and height" do
    first_ids, first_links = star("X", 25)
    second_ids, second_links = star("Y", 9)
    layout = Fd::ClusterLayout.new(cluster(first_ids + second_ids, first_links + second_links + [["X3", "Y4", 6.0]]))

    layout.points.each_value do |point|
      assert point.x.between?(0, layout.width) && point.y.between?(0, layout.height)
    end
  end

  test "accounts without links form a separate group with nil hub" do
    ids, links = star("G", 4)
    ids += %w[L1 L2 L3]
    layout = Fd::ClusterLayout.new(cluster(ids, links))

    assert_equal 2, layout.groups.size
    unlinked = layout.groups.find { |group| group.hub.nil? }
    assert_equal %w[L1 L2 L3], unlinked.others
    assert layout.points.values_at("L1", "L2", "L3").none?(&:hub)
  end
end

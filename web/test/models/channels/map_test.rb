require "test_helper"

class Channels::MapTest < ActiveSupport::TestCase
  test "the four quadrants name themselves by where a channel sits" do
    {
      [true, true] => "working", [true, false] => "landing, not staying",
      [false, true] => "small and sticky", [false, false] => "quiet"
    }.each do |(across, above), label|
      assert_equal label, Channels::Map.phase(across: across, above: above).first
    end
  end

  test "a channel exactly on a dividing line counts as above it, not below" do
    assert_equal "working", Channels::Map.phase(across: true, above: true).first
  end

  test "every quadrant draws in its own ink" do
    inks = Channels::Map::QUADRANTS.values.map(&:last)

    assert_equal inks.uniq.length, inks.length, "two quadrants share a colour"
  end

  test "the median splits an odd and an even list" do
    assert_equal 5, Channels::Map.median([9, 1, 5])
    assert_equal 3.0, Channels::Map.median([1, 5, 2, 4])
    assert_equal 0, Channels::Map.median([])
  end

  test "a share is a percentage, and an empty denominator has none" do
    assert_equal 33.0, Channels::Map.share(0.33)
    assert_nil Channels::Map.share(nil)
    assert_equal 25.0, Channels::Map.share_of(1, 4)
    assert_nil Channels::Map.share_of(1, 0)
  end

  test "the floor is the one the rest of the dashboard already uses" do
    assert_equal HomeHelper::MIN_SAMPLE, Channels::Map.floor
  end

  test "a report with no channel above the floor renders its empty state" do
    assert_not Channels::Map::Report.new(points: [], floor: Channels::Map.floor).any?
  end

  test "points carry only what the chart draws, never the channel id" do
    point = Channels::Map::Point.new(channel_id: "C1", name: "lounge", x: 1, y: 2, n: 3, ink: 2,
      phase: "working")

    assert_not_includes point.as_json.keys, :channel_id
    assert_equal %i[name x y n ink phase], point.as_json.keys
  end
end

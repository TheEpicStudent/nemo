require "test_helper"

class Channels::MapTest < ActiveSupport::TestCase
  test "phase returns the label for each across and above pair" do
    {
      [true, true] => "high volume, high retention", [true, false] => "high volume, low retention",
      [false, true] => "low volume, high retention", [false, false] => "low volume, low retention"
    }.each do |(across, above), label|
      assert_equal label, Channels::Map.phase(across: across, above: above).first
    end
  end

  test "phase with across and above true returns the high volume high retention label" do
    assert_equal "high volume, high retention", Channels::Map.phase(across: true, above: true).first
  end

  test "QUADRANTS colors are unique" do
    colors = Channels::Map::QUADRANTS.values.map(&:last)

    assert_equal colors.uniq.length, colors.length, "two quadrants share a colour"
  end

  test "median handles odd and even and empty lists" do
    assert_equal 5, Channels::Map.median([9, 1, 5])
    assert_equal 3.0, Channels::Map.median([1, 5, 2, 4])
    assert_equal 0, Channels::Map.median([])
  end

  test "share and share_of return a percentage and nil for a nil or zero denominator" do
    assert_equal 33.0, Channels::Map.share(0.33)
    assert_nil Channels::Map.share(nil)
    assert_equal 25.0, Channels::Map.share_of(1, 4)
    assert_nil Channels::Map.share_of(1, 0)
  end

  test "floor equals HomeHelper::MIN_SAMPLE" do
    assert_equal HomeHelper::MIN_SAMPLE, Channels::Map.floor
  end

  test "Report#any? is false without points" do
    assert_not Channels::Map::Report.new(points: [], floor: Channels::Map.floor).any?
  end

  test "last30 cohort is the default with a rolling 30 day label and window" do
    assert_equal "last30", Analytics::MartNewcomerChannels::DEFAULT_COHORT
    last30 = Analytics::MartNewcomerChannels::Cohort.new(key: "last30", order: 0,
      ends_on: Date.new(2026, 9, 12), mature: false)

    assert last30.default?
    assert_equal "Last 30 days", last30.label
    assert_equal "30 days to 12 Sep 2026", last30.window
  end

  test "month cohort label and window use the month name" do
    month = Analytics::MartNewcomerChannels::Cohort.new(key: "2026-07", order: 1,
      starts_on: Date.new(2026, 7, 1), ends_on: Date.new(2026, 7, 31), mature: true)

    assert_not month.default?
    assert_equal "Jul 2026", month.label
    assert_equal "July 2026", month.window
  end

  test "cohort with an unknown key falls back to the default cohort" do
    offered = Analytics::MartNewcomerChannels.cohorts
    skip "the corpus has no newcomer cohorts" if offered.empty?

    fallback = Analytics::MartNewcomerChannels.cohort("nonsense")
    assert_includes offered.map(&:key), fallback&.key
    assert_equal "last30", fallback.key if offered.any?(&:default?)
  end

  test "Point#as_json omits channel_id and keeps the chart keys" do
    point = Channels::Map::Point.new(channel_id: "C1", name: "lounge", x: 1, y: 2, n: 3, series_color: 2,
      phase: "high volume, high retention")

    assert_not_includes point.as_json.keys, :channel_id
    assert_equal %i[name x y n seriesColor phase], point.as_json.keys
  end
end

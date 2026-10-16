require "test_helper"

class Channels::WindowTest < ActiveSupport::TestCase
  LOADED_START = Date.new(2026, 8, 7)
  LOADED_END = Date.new(2026, 9, 5)
  EDGE = Date.new(2026, 9, 5)

  def build(days, loaded_start: LOADED_START, loaded_end: LOADED_END, edge: EDGE,
            start_on: nil, end_on: nil)
    Channels::Window.new(days: days, loaded_start: loaded_start,
      loaded_end: loaded_end, edge: edge, start_on: start_on, end_on: end_on)
  end

  test "loaded_days counts the loaded range inclusively and choices includes it" do
    w = build(nil)

    assert_equal 30, w.loaded_days
    assert_equal [7, 30, 90], w.choices
  end

  test "choices includes loaded_days when it matches no preset" do
    w = build(nil, loaded_start: Date.new(2026, 9, 2), loaded_end: Date.new(2026, 9, 4))

    assert_equal 3, w.loaded_days
    assert_equal [3, 7, 30, 90], w.choices
  end

  test "without days or custom range window is loaded and uses loaded measure_sql" do
    w = build(nil)

    assert_equal 30, w.days
    assert w.loaded?
    assert_nil w.join
    assert_nil w.requested_days
    assert_equal "r.messages_posted_by_members", w.measure_sql
    assert_empty w.measures
  end

  test "days equal to loaded_days is loaded" do
    assert build("30").loaded?, "days equal to loaded_days must not roll up"
  end

  test "preset days rolls up over a range ending at edge with rolled measure_sql" do
    w = build("7")

    assert_not w.loaded?
    assert_equal 7, w.days
    assert_equal Date.new(2026, 8, 30), w.start_date
    assert_equal EDGE, w.end_date
    assert_equal 7, w.requested_days
    assert_equal "a.range_messages", w.measure_sql
    assert_equal({ "messages" => "a.range_messages" }, w.measures)
  end

  test "join renders sum over BETWEEN dates grouped by channel_id" do
    sql = build("90").join

    assert_includes sql, "sum(messages_posted_by_members) AS range_messages"
    assert_includes sql, "BETWEEN '2026-06-08' AND '2026-09-05'"
    assert_includes sql, "GROUP BY channel_id"
  end

  test "days with an unsupported value falls back to loaded days" do
    %w[1 45 1000 0 -7 abc].each do |bad|
      assert_equal 30, build(bad).days, "#{bad.inspect} is not an accepted days value"
    end
  end

  test "without edge any days stays loaded and is not adjustable" do
    w = build("90", edge: nil)

    assert w.loaded?
    assert_nil w.join
    assert_equal LOADED_START, w.start_date
    assert_equal LOADED_END, w.end_date
    assert_not w.adjustable?, "adjustable? is false without edge"
  end

  test "adjustable? is true with edge and several choices" do
    assert build(nil).adjustable?
  end

  test "without loaded range choices are presets only and window is not loaded" do
    w = build(nil, loaded_start: nil, loaded_end: nil)

    assert_nil w.loaded_days
    assert_equal [7, 30, 90], w.choices
    assert_equal 7, w.days
    assert_not w.loaded?
  end

  test "column aliases the loaded measure as range_messages and uses the rolled measure" do
    assert_equal "r.messages_posted_by_members AS range_messages", build(nil).column
    assert_equal "a.range_messages", build("7").column
  end

  test "custom range overrides preset days and rolls up over its own dates" do
    w = build("7", start_on: Date.new(2026, 8, 20), end_on: Date.new(2026, 8, 29))

    assert w.custom?
    assert_not w.loaded?
    assert_equal Date.new(2026, 8, 20), w.start_date
    assert_equal Date.new(2026, 8, 29), w.end_date
    assert_equal 10, w.days
    assert_includes w.join, "BETWEEN '2026-08-20' AND '2026-08-29'"
  end

  test "custom range exposes requested_start and requested_end and nil requested_days" do
    w = build(nil, start_on: Date.new(2026, 8, 20), end_on: Date.new(2026, 8, 29))

    assert_nil w.requested_days
    assert_equal Date.new(2026, 8, 20), w.requested_start
    assert_equal Date.new(2026, 8, 29), w.requested_end
  end

  test "preset days is not custom and has nil requested_start and requested_end" do
    w = build("7")

    assert_not w.custom?
    assert_nil w.requested_start
    assert_nil w.requested_end
  end

  test "custom range beyond bounds is clamped to floor and ceiling" do
    w = build(nil, start_on: Date.new(2020, 1, 1), end_on: Date.new(2030, 1, 1))

    assert_equal w.ceiling, w.end_date
    assert_equal w.floor, w.start_date
  end

  test "custom range with end before start keeps start_date not after end_date" do
    w = build(nil, start_on: Date.new(2026, 9, 4), end_on: Date.new(2026, 8, 20))

    assert_operator w.start_date, :<=, w.end_date
  end

  test "custom range with only end_on is custom and keeps end_date" do
    w = build(nil, end_on: Date.new(2026, 8, 29))

    assert w.custom?
    assert_equal Date.new(2026, 8, 29), w.end_date
  end
end

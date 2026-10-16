require "test_helper"

class Community::CalendarTest < ActiveSupport::TestCase
  def build(rows, today: Date.new(2026, 9, 18), day_rows: nil, **overrides)
    window_end = today.end_of_week(:monday)
    posted = rows.map { |on, messages, _channels, _replies| [on, messages, messages] }
    Community::Calendar.new(
      day_rows: day_rows || rows.map { |on, messages, channels, replies| [on, channels, replies, messages] },
      posted: posted, window_start: window_end - (53 * 7 - 1),
      window_end: window_end, today: today, **overrides)
  end

  test "cells covers 53 weeks of days and any? is false without rows" do
    cal = build([])

    assert_equal 53 * 7, cal.cells.size
    assert_equal cal.window_start, cal.cells.first.on
    assert_not cal.any?
  end

  test "step scales to the peak of each calendar" do
    low_volume = build((1..40).map { |n| [Date.new(2026, 9, 1) - n, (n % 4) + 1, 1, 0] })
    high_volume = build((1..40).map { |n| [Date.new(2026, 9, 1) - n, n * 25, 9, 4] })

    assert_equal 5, low_volume.cells.map(&:step).max, "low volume calendar does not reach the top step"
    assert_equal 5, high_volume.cells.map(&:step).max
    assert_operator high_volume.peak, :>, low_volume.peak
  end

  test "cell without a row has step 0 and active_days counts one day" do
    cal = build([[Date.new(2026, 9, 14), 12, 3, 2]])

    cell = cal.cells.find { |cell| cell.on == Date.new(2026, 9, 14) }
    empty_cell = cal.cells.find { |cell| cell.on == Date.new(2026, 9, 15) }

    assert_operator cell.step, :>, 0
    assert_equal 0, empty_cell.step
    assert_equal 1, cal.active_days
  end

  test "cell before first_post_on is before? and the first post day is measured?" do
    first = Date.new(2026, 3, 9)
    cal = build([[first, 4, 1, 0]], first_post_on: first)

    assert cal.cells.find { |cell| cell.on == first - 1 }.before?
    assert cal.cells.find { |cell| cell.on == first }.measured?
  end

  test "cell after today is future? and today is measured?" do
    today = Date.new(2026, 9, 18)
    cal = build([], today: today)

    assert cal.cells.find { |cell| cell.on == today + 1 }.future?
    assert cal.cells.find { |cell| cell.on == today }.measured?
  end

  test "run_columns spans the columns of run_from and run_to" do
    cal = build([], run_from: Date.new(2026, 9, 1), run_to: Date.new(2026, 9, 18))
    from, to = cal.run_columns

    assert_operator from, :<=, to
    assert_equal cal.column_of(Date.new(2026, 9, 1)), from
    assert_equal 53, to
  end

  test "run_columns is nil without a run" do
    assert_nil build([]).run_columns
  end

  test "cell from posted without day_rows has a step and counts elsewhere and is unarchived" do
    on = Date.new(2026, 9, 12)
    cal = Community::Calendar.new(day_rows: [], posted: [[on, 55, 32]],
      window_start: Date.new(2026, 9, 18).end_of_week(:monday) - (53 * 7 - 1),
      window_end: Date.new(2026, 9, 18).end_of_week(:monday), today: Date.new(2026, 9, 18))

    cell = cal.cells.find { |cell| cell.on == on }
    assert_operator cell.step, :>, 0, "posted-only cell has step 0"
    assert_equal 55, cell.messages
    assert_equal 32, cell.in_channels
    assert_equal 23, cell.elsewhere
    assert_equal 0, cell.channels
    assert cell.unarchived?, "posted-only cell is not unarchived"
    assert_equal 1, cal.active_days
  end

  test "cell from day_rows without posted takes messages from day_rows and has a step" do
    on = Date.new(2026, 9, 17)
    cal = Community::Calendar.new(day_rows: [[on, 2, 1, 6]], posted: [],
      window_start: Date.new(2026, 9, 18).end_of_week(:monday) - (53 * 7 - 1),
      window_end: Date.new(2026, 9, 18).end_of_week(:monday), today: Date.new(2026, 9, 18))

    cell = cal.cells.find { |cell| cell.on == on }
    assert_equal 6, cell.messages, "messages differs from the day_rows count"
    assert_equal 6, cell.in_channels
    assert_equal 0, cell.elsewhere
    assert_operator cell.step, :>, 0
  end

  test "cell from day_rows and posted takes channels and replies from day_rows and is archived" do
    on = Date.new(2026, 9, 12)
    cal = Community::Calendar.new(day_rows: [[on, 4, 9, 20]], posted: [[on, 20, 20]],
      window_start: Date.new(2026, 9, 18).end_of_week(:monday) - (53 * 7 - 1),
      window_end: Date.new(2026, 9, 18).end_of_week(:monday), today: Date.new(2026, 9, 18))

    cell = cal.cells.find { |cell| cell.on == on }
    assert_equal 20, cell.messages
    assert_equal 4, cell.channels
    assert_equal 9, cell.replies
    assert_equal 0, cell.elsewhere
    assert_not cell.unarchived?
  end

  test "run_columns follows the posted days over run_from and run_to" do
    today = Date.new(2026, 9, 18)
    posted_days = (0..20).map { |n| [today - n, 5, 5] }
    cal = Community::Calendar.new(day_rows: [], posted: posted_days,
      window_start: today.end_of_week(:monday) - (53 * 7 - 1),
      window_end: today.end_of_week(:monday), today: today,
      run_from: Date.new(2026, 1, 1), run_to: Date.new(2026, 1, 2))

    assert_equal cal.column_of(today - 20), cal.run_columns.first
    assert_equal cal.column_of(today), cal.run_columns.last
  end

  test "months spans sum to 53 columns starting at column 1" do
    cal = build([])

    assert_equal 53, cal.months.sum(&:span)
    assert_equal 1, cal.months.first.from
  end
end

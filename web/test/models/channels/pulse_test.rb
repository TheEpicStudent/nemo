require "test_helper"

class Channels::PulseTest < ActiveSupport::TestCase
  def day(ds, **overrides)
    Analytics::MartChannelDay.new({ ds: Date.parse(ds), messages: 0, member_messages: 0,
                                    bot_messages: 0, authors: 0, questions: 0,
                                    questions_with_replies: 0, thread_replies: 0,
                                    thread_roots: 0, replies_on_roots: 0, reactions: 0,
                                    unreacted: 0, text_length_total: 0, with_link: 0,
                                    with_file: 0, emoji_only: 0, substantive: 0,
                                    with_mention: 0 }.merge(overrides))
  end

  def build(rows, from: "2026-09-01", to: "2026-09-03")
    Channels::Pulse.new(channel_id: "C1", from: Date.parse(from), to: Date.parse(to), rows: rows)
  end

  test "member_messages and messages sum over the days in the range" do
    pulse = build([day("2026-09-01", member_messages: 10, messages: 12),
                   day("2026-09-02", member_messages: 5, messages: 6)])

    assert_equal 15, pulse.member_messages
    assert_equal 18, pulse.messages
  end

  test "posters_per_day averages authors over the days" do
    pulse = build([day("2026-09-01", authors: 10), day("2026-09-02", authors: 20)])

    assert_equal 15, pulse.posters_per_day
  end

  test "posters_per_day is nil for an empty range" do
    assert_nil build([]).posters_per_day
  end

  test "answered_share is nil for no rows and 50.0 for 2 of 4 questions" do
    assert_nil build([]).answered_share
    assert_equal 50.0, build([day("2026-09-01", questions: 4, questions_with_replies: 2)])
      .answered_share
  end

  test "share_series is nil on days without messages" do
    pulse = build([day("2026-09-02", messages: 10, with_link: 4)])

    assert_equal [nil, 40.0, nil], pulse.share_series(:with_link)
  end

  test "share_series divides each day by its own messages" do
    pulse = build([day("2026-09-01", messages: 4, substantive: 1),
                   day("2026-09-02", messages: 10, substantive: 9)])

    assert_equal [25.0, 90.0, nil], pulse.share_series(:substantive)
  end

  test "labels has one entry per series row starting at from" do
    pulse = build([day("2026-09-02", messages: 1)])

    assert_equal pulse.series.size, pulse.labels.size
    assert_equal "2026-09-01", pulse.labels.first
  end

  test "series has a row for every day including days without messages" do
    pulse = build([day("2026-09-02", member_messages: 5)])
    series = pulse.series

    assert_equal 3, series.size
    assert_equal [0, 5, 0], series.map(&:member_messages)
    assert_equal Date.parse("2026-09-01"), series.first.ds
  end

  test "series rows expose reactions per day" do
    pulse = build([day("2026-09-02", reactions: 7)])

    assert_equal [0, 7, 0], pulse.series.map(&:reactions)
  end

  test "prior covers the same number of days ending the day before from" do
    pulse = build([], from: "2026-09-08", to: "2026-09-14")

    assert_equal 7, pulse.days
    assert_equal Date.parse("2026-09-01"), pulse.prior.from
    assert_equal Date.parse("2026-09-07"), pulse.prior.to
  end

  test "change is nil when the prior window has no rows" do
    pulse = build([day("2026-09-01", member_messages: 10)])
    pulse.prior.instance_variable_set(:@rows, [])

    assert_nil pulse.change(:member_messages)
  end

  test "change returns the percentage against the prior window" do
    pulse = build([day("2026-09-01", member_messages: 150)])
    pulse.prior.instance_variable_set(:@rows, [day("2026-08-29", member_messages: 100)])

    assert_equal 50.0, pulse.change(:member_messages)
  end

  test "posters_change compares the daily average of authors" do
    pulse = build([day("2026-09-01", authors: 12), day("2026-09-02", authors: 18)])
    pulse.prior.instance_variable_set(:@rows, [day("2026-08-30", authors: 10)])

    assert_equal 15, pulse.posters_per_day
    assert_equal 50.0, pulse.posters_change
  end

  test "posters_change is nil when the prior window has no rows" do
    pulse = build([day("2026-09-01", authors: 12)])
    pulse.prior.instance_variable_set(:@rows, [])

    assert_nil pulse.posters_change
  end

  test "replies_per_thread is nil without thread_roots" do
    assert_nil build([day("2026-09-01", replies_on_roots: 9)]).replies_per_thread
    assert_equal 3.0, build([day("2026-09-01", thread_roots: 3, replies_on_roots: 9)])
      .replies_per_thread
  end

  test "average_length divides text_length_total by messages" do
    pulse = build([day("2026-09-01", messages: 2, text_length_total: 100),
                   day("2026-09-02", messages: 2, text_length_total: 300)])

    assert_equal 100, pulse.average_length
  end
end

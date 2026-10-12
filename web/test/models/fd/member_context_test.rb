require "test_helper"

class Fd::MemberContextTest < ActiveSupport::TestCase
  SUBJECT_ID = "USUB".freeze

  def context_for(user_id = SUBJECT_ID)
    Fd::MemberContext.for([user_id]).fetch(user_id)
  end

  def member_window(at)
    Analytics::MemberWindow.new(user_id: SUBJECT_ID, last_active_at: at,
      source: Analytics::MemberWindow::LIFETIME_SOURCE)
  end

  def last_activity(post: nil, login: nil)
    Fd::MemberSeen.new(user_id: SUBJECT_ID, last_post_at: post, last_login_at: login)
  end

  def build_context(window:, seen:)
    Fd::MemberContext.new(SUBJECT_ID, nil, window, seen)
  end

  test "the newest message wins when the analytics window is behind it" do
    window_at = 3.days.ago.change(usec: 0)
    post_at = 1.hour.ago.change(usec: 0)

    person = build_context(window: member_window(window_at), seen: last_activity(post: post_at))

    assert_equal post_at, person.last_active_at
  end

  test "the analytics window wins when somebody was about without posting" do
    window_at = 1.hour.ago.change(usec: 0)
    post_at = 9.days.ago.change(usec: 0)

    person = build_context(window: member_window(window_at), seen: last_activity(post: post_at))

    assert_equal window_at, person.last_active_at
  end

  test "a login after the last message counts as activity" do
    post_at = 6.days.ago.change(usec: 0)
    login_at = 10.minutes.ago.change(usec: 0)

    person = build_context(window: member_window(4.days.ago), seen: last_activity(post: post_at, login: login_at))

    assert_equal login_at, person.last_active_at
    assert_equal post_at, person.last_posted_at
  end

  test "either source alone is enough" do
    at = 2.hours.ago.change(usec: 0)

    assert_equal at, build_context(window: member_window(at), seen: nil).last_active_at
    assert_equal at, build_context(window: nil, seen: last_activity(post: at)).last_active_at
    assert_equal at, build_context(window: nil, seen: last_activity(login: at)).last_active_at
    assert_nil build_context(window: nil, seen: nil).last_active_at
  end

  test "a window that knows nothing does not hide a message we hold" do
    at = 5.minutes.ago.change(usec: 0)

    person = build_context(window: member_window(nil), seen: last_activity(post: at))

    assert_equal at, person.last_active_at
    assert_equal at, person.last_posted_at
  end

  test "a login is not a message" do
    person = build_context(window: nil, seen: last_activity(login: 1.hour.ago))

    assert_nil person.last_posted_at
  end

  test "looking somebody up reads every source" do
    assert_nothing_raised { context_for }
  end

  test "a member the warehouse has not met yet takes their tenure from the day they joined" do
    joined = 2.days.ago.change(usec: 0)

    person = Fd::MemberContext.new(SUBJECT_ID, nil, nil, nil, joined)

    assert_equal joined, person.cohort_at
    assert_equal 2, person.tenure_days
  end

  test "the warehouse cohort wins over the join day when both are known" do
    cohort = 400.days.ago.change(usec: 0)
    member = Analytics::DimMember.new(user_id: SUBJECT_ID, cohort_at: cohort)

    person = Fd::MemberContext.new(SUBJECT_ID, member, nil, nil, 1.day.ago)

    assert_equal cohort, person.cohort_at
  end
end

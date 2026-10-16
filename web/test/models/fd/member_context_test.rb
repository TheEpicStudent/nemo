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

  test "last_active_at uses the post time when the window is older" do
    window_at = 3.days.ago.change(usec: 0)
    post_at = 1.hour.ago.change(usec: 0)

    context = build_context(window: member_window(window_at), seen: last_activity(post: post_at))

    assert_equal post_at, context.last_active_at
  end

  test "last_active_at uses the window time when the post is older" do
    window_at = 1.hour.ago.change(usec: 0)
    post_at = 9.days.ago.change(usec: 0)

    context = build_context(window: member_window(window_at), seen: last_activity(post: post_at))

    assert_equal window_at, context.last_active_at
  end

  test "last_active_at uses a later login and last_posted_at stays the post time" do
    post_at = 6.days.ago.change(usec: 0)
    login_at = 10.minutes.ago.change(usec: 0)

    context = build_context(window: member_window(4.days.ago), seen: last_activity(post: post_at, login: login_at))

    assert_equal login_at, context.last_active_at
    assert_equal post_at, context.last_posted_at
  end

  test "last_active_at uses any single source and is nil with none" do
    at = 2.hours.ago.change(usec: 0)

    assert_equal at, build_context(window: member_window(at), seen: nil).last_active_at
    assert_equal at, build_context(window: nil, seen: last_activity(post: at)).last_active_at
    assert_equal at, build_context(window: nil, seen: last_activity(login: at)).last_active_at
    assert_nil build_context(window: nil, seen: nil).last_active_at
  end

  test "last_active_at and last_posted_at use the post when the window time is nil" do
    at = 5.minutes.ago.change(usec: 0)

    context = build_context(window: member_window(nil), seen: last_activity(post: at))

    assert_equal at, context.last_active_at
    assert_equal at, context.last_posted_at
  end

  test "last_posted_at is nil with only a login" do
    context = build_context(window: nil, seen: last_activity(login: 1.hour.ago))

    assert_nil context.last_posted_at
  end

  test "MemberContext.for with one user id does not raise" do
    assert_nothing_raised { context_for }
  end

  test "cohort_at and tenure_days use the join time without a warehouse member" do
    joined = 2.days.ago.change(usec: 0)

    context = Fd::MemberContext.new(SUBJECT_ID, nil, nil, nil, joined)

    assert_equal joined, context.cohort_at
    assert_equal 2, context.tenure_days
  end

  test "cohort_at prefers the warehouse cohort_at over the join time" do
    cohort = 400.days.ago.change(usec: 0)
    member = Analytics::DimMember.new(user_id: SUBJECT_ID, cohort_at: cohort)

    context = Fd::MemberContext.new(SUBJECT_ID, member, nil, nil, 1.day.ago)

    assert_equal cohort, context.cohort_at
  end
end

require "test_helper"

class Fd::MemberGuardTest < ActiveSupport::TestCase
  def open!(**over)
    Fd::MemberGuard.open!(
      **{ kind: "shush", subject_id: "USUB", by: "UMOD", reason: "being awful",
          expires_at: 7.days.from_now }.merge(over)
    )
  end

  test "open! returns nil for a second live guard and keeps the transaction usable" do
    Fd::MemberGuard.transaction do
      assert open!
      assert_nil open!
      assert_equal 1, Fd::MemberGuard.count
      assert Fd::MemberGuard.create!(kind: "channel_ban", subject_id: "USUB",
        channel_id: "C1", opened_by: "UMOD", reason: "still writable")
    end
  end

  test "attach_to! succeeds only while case_id is nil" do
    first = make_case
    second = make_case
    guard = open!
    assert guard.attach_to!(first.id)
    assert_equal first.id, guard.case_id
    assert_nil guard.attach_to!(second.id)
    assert_equal first.id, guard.reload.case_id
  end

  test "lift! returns nil on the second call and keeps the first lifted_by" do
    guard = open!
    assert guard.lift!(by: "UMOD", reason: "enough")
    assert_nil guard.lift!(by: "USOMEBODY")
    assert_equal "UMOD", guard.reload.lifted_by
  end

  test "set_expiry! and attach_to! return nil on a lifted guard" do
    guard = open!
    guard.lift!(by: "UMOD")
    assert_nil guard.set_expiry!(30.days.from_now)
    assert_nil guard.attach_to!(make_case.id)
  end

  test "a guard in state lifting is active and blocks open!" do
    guard = open!
    guard.update!(state: "lifting", lifted_by: "UMOD")
    assert_includes Fd::MemberGuard.active, guard
    assert_nil open!
  end

  test "evaluate_standing reports ORPHANED and ON_CASE and ELSEWHERE for the given case" do
    current_case = make_case
    other = make_case
    guard = open!
    assert_equal Fd::MemberGuard::ORPHANED,
      Fd::MemberGuard.evaluate_standing("shush", "USUB", case_id: current_case.id).reads

    guard.attach_to!(current_case.id)
    assert_equal Fd::MemberGuard::ON_CASE,
      Fd::MemberGuard.evaluate_standing("shush", "USUB", case_id: current_case.id).reads
    assert_equal Fd::MemberGuard::ELSEWHERE,
      Fd::MemberGuard.evaluate_standing("shush", "USUB", case_id: other.id).reads
  end

  test "evaluate_standing is not enforceable for warning and has no guard for a nil subject" do
    open!
    warning_standing = Fd::MemberGuard.evaluate_standing("warning", "USUB", case_id: make_case.id)
    assert_not warning_standing.enforceable?
    assert_nil warning_standing.guard

    nil_subject_standing = Fd::MemberGuard.evaluate_standing("shush", nil, case_id: make_case.id)
    assert nil_subject_standing.enforceable?
    assert_nil nil_subject_standing.guard
  end
end

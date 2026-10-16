require "test_helper"

class FdActionSettleTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
    @kase = make_case(opened_at: 3.days.ago)
  end

  def guard!(**over)
    Fd::MemberGuard.create!({
      kind: "shush", subject_id: "USUB", opened_by: "UMOD",
      reason: "being awful", expires_at: 7.days.from_now
    }.merge(over))
  end

  def act(**params)
    post fd_case_actions_path(@kase), params: {
      type_key: "shush", target_user_id: "USUB", reason: "would not let it go",
      expires_on: 7.days.from_now.to_date.to_s
    }.merge(params)
  end

  def guards = Fd::MemberGuard.for_subject("USUB")

  def last_action = @kase.actions.order(:id).last

  def audit_entries(verb)
    Fd::AuditEntry.where(entity_type: "member_guard", verb: verb)
  end

  test "create action opens a pending nemo guard and one opened audit entry" do
    act
    guard = guards.sole
    assert_equal "shush", guard.kind
    assert_equal @kase.id, guard.case_id
    assert_equal "nemo", guard.enforced_by
    assert_equal "pending", guard.enforcement_status
    assert_equal guard.id, last_action.guard_id
    assert_equal 1, audit_entries("opened").count
  end

  test "create warning action logs the action and opens no guard" do
    act(type_key: "warning", expires_on: nil)
    assert_empty guards
    assert_nil last_action.guard_id
    assert_equal "warning", last_action.type_key
  end

  test "create shush action stores no channel_id on the guard" do
    act(channel_id: "C0266FRGV")
    assert_nil guards.sole.channel_id
  end

  test "create channel_ban action stores channel_id on the guard" do
    act(type_key: "channel_ban", channel_id: "C0266FRGV")
    assert_equal "C0266FRGV", guards.sole.channel_id
  end

  test "create action with standing_guard_id attaches the guard and opens no second guard" do
    guard = guard!
    act(standing_guard_id: guard.id)

    assert_equal @kase.id, guard.reload.case_id
    assert_equal 1, guards.count
    assert_equal guard.id, last_action.guard_id
    assert_equal "shush", last_action.type_key
    assert_equal 1, audit_entries("attached").count
    assert_empty audit_entries("opened")
  end

  test "create action with standing_guard_id copies guard attributes over form params" do
    guard = guard!(kind: "channel_ban", channel_id: "C0266FRGV",
      reason: "off topic", expires_at: 30.days.from_now)
    act(standing_guard_id: guard.id, type_key: "warning", reason: "something else")

    assert_equal "channel_ban", last_action.type_key
    assert_equal "off topic", last_action.reason
    assert_equal "C0266FRGV", last_action.details["channel_id"]
    assert_equal guard.expires_at.to_i, last_action.expires_at.to_i
  end

  test "create action with guard on another case links it and keeps its case_id" do
    other = make_case
    guard = guard!(case_id: other.id)
    act(standing_guard_id: guard.id)

    assert_equal other.id, guard.reload.case_id, "guard case_id is unchanged"
    assert_equal guard.id, last_action.guard_id
    assert_empty audit_entries("attached")
  end

  test "create action with guard already on this case alerts and logs no action" do
    guard = guard!(case_id: @kase.id)
    act(standing_guard_id: guard.id)

    assert_equal 0, @kase.actions.count
    assert_empty audit_entries("attached")
    assert_match(/already on this case/, flash[:alert])
  end

  test "create action with standing_guard_id accepts blank type_key and reason and expires_on" do
    guard = guard!
    act(standing_guard_id: guard.id, type_key: "", reason: "", expires_on: "")

    assert_equal guard.id, last_action.guard_id
    assert_equal 1, @kase.actions.count
  end

  test "create action with guard of another subject does not attach it" do
    guard = guard!(subject_id: "USOMEBODY")
    act(standing_guard_id: guard.id)

    assert_nil guard.reload.case_id
    assert_equal "shush", last_action.type_key, "a new action is logged"
    assert_not_equal guard.id, last_action.guard_id
  end

  test "create action with lifted guard does not attach it" do
    guard = guard!(state: "lifted", lifted_at: Time.current, lifted_by: "UMOD")
    act(standing_guard_id: guard.id)

    assert_nil guard.reload.case_id
    assert_not_equal guard.id, last_action.guard_id
  end

  test "create action of the same kind on the case opens no second guard" do
    guard!(case_id: @kase.id)
    act
    assert_equal 1, guards.count
  end

  test "create action without permission writes no guard and no action" do
    revoke_roles!("UME")
    grant_role!("UME", "gardener")
    act
    assert_empty guards
    assert_empty @kase.actions
  end

  test "create action twice with guard on another case logs one action and alerts" do
    other = make_case
    guard = guard!(case_id: other.id)
    act(standing_guard_id: guard.id)
    act(standing_guard_id: guard.id)

    assert_equal 1, @kase.actions.count
    assert_equal other.id, guard.reload.case_id
    assert_match(/already logged on this case/, flash[:alert])
  end

  test "create action twice with guard without case attaches once and alerts" do
    guard = guard!(case_id: nil)
    act(standing_guard_id: guard.id)
    act(standing_guard_id: guard.id)

    assert_equal 1, @kase.actions.count
    assert_equal @kase.id, guard.reload.case_id
    assert_match(/already on this case/, flash[:alert])
  end
end

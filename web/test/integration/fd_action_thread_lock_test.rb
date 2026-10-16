require "test_helper"

class FdActionThreadLockTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
    @kase = make_case(subject: "USUB")
  end

  def lock!(**over)
    Fd::ThreadGuard.create!({
      kind: "lock", channel_id: "C0266FRGV", thread_ts: "1700000000.000100",
      opened_by: "UMOD", reason: "it was going nowhere", state: "running",
      expires_at: 3.days.from_now, case_id: nil
    }.merge(over))
  end

  def log(**params)
    post fd_case_actions_path(@kase), params: { type_key: "locked_thread" }.merge(params)
  end

  def actions = @kase.actions.reload

  test "action create with a lock records the lock on the case with no target user" do
    guard = lock!
    log(thread_guard_id: guard.id)

    action = actions.sole
    assert_equal "locked_thread", action.type_key
    assert_nil action.target_user_id
    assert_equal guard.id, action.thread_guard_id
    assert_equal "C0266FRGV", action.details["channel_id"]
    assert_equal "1700000000.000100", action.details["thread_ts"]
  end

  test "action create copies reason and expires_at from the lock over the typed reason" do
    guard = lock!
    log(thread_guard_id: guard.id, reason: "typed into the box and ignored")

    action = actions.sole
    assert_equal "it was going nowhere", action.reason
    assert_equal guard.expires_at.to_i, action.expires_at.to_i
  end

  test "action create attaches a lock without a case and writes an attached audit entry" do
    guard = lock!(case_id: nil)
    log(thread_guard_id: guard.id)

    assert_equal @kase.id, guard.reload.case_id
    assert_equal 1, Fd::AuditEntry.where(entity_type: "thread_guard", verb: "attached").count
    assert_match(/thread attached/, flash[:notice])
  end

  test "action create keeps case_id of a lock attached to another case" do
    other = make_case
    guard = lock!(case_id: other.id)
    log(thread_guard_id: guard.id)

    assert_equal other.id, guard.reload.case_id
    assert_equal 1, actions.count
    assert_no_match(/now on this case/, flash[:notice].to_s)
  end

  test "action create with a lock ignores target_user_id and keeps subject_user_ids" do
    guard = lock!
    subject_ids = @kase.subject_user_ids.sort
    log(thread_guard_id: guard.id, target_user_id: "UNEW")

    assert_nil actions.sole.target_user_id
    assert_equal subject_ids, @kase.reload.subject_user_ids.sort
  end

  test "action create without thread_guard_id creates no action and alerts" do
    log(thread_guard_id: "")

    assert_equal 0, actions.count
    assert_match(/Select a thread lock/, flash[:alert])
  end

  test "action create with a done lock creates no action and alerts" do
    guard = lock!(state: "done")
    log(thread_guard_id: guard.id)

    assert_equal 0, actions.count
    assert_match(/Select a thread lock/, flash[:alert])
  end

  test "action create with the same lock twice creates one action" do
    guard = lock!
    log(thread_guard_id: guard.id)
    log(thread_guard_id: guard.id)

    assert_equal 1, actions.count
    assert_match(/already on this case/, flash[:alert])
  end

  test "case action form renders a lock attached to the case disabled" do
    guard = lock!(case_id: @kase.id)
    get fd_case_path(@kase, do: "action")
    body = response.body

    assert_match(/name="thread_guard_id" value="#{guard.id}"/, body)
    assert_select %(input[name="thread_guard_id"][value="#{guard.id}"][disabled])
    assert_match(/already on this case/, body)
  end

  test "action create with a lock attached to the case creates no action" do
    guard = lock!(case_id: @kase.id)
    log(thread_guard_id: guard.id)

    assert_equal 0, actions.count
    assert_match(/already on this case/, flash[:alert])
  end

  test "case action form renders a lock of another case disabled after it is logged here" do
    other = make_case
    guard = lock!(case_id: other.id)
    log(thread_guard_id: guard.id)
    get fd_case_path(@kase, do: "action")

    assert_select %(input[name="thread_guard_id"][value="#{guard.id}"][disabled])
    assert_match(/already logged on this case/, response.body)
  end

  test "case action form renders a lock of another case enabled" do
    other = make_case
    guard = lock!(case_id: other.id)
    get fd_case_path(@kase, do: "action")

    assert_select %(input[name="thread_guard_id"][value="#{guard.id}"][disabled]), false
  end

  test "action create with a lock of another case twice creates one action" do
    other = make_case
    guard = lock!(case_id: other.id)
    log(thread_guard_id: guard.id)
    log(thread_guard_id: guard.id)

    assert_equal 1, actions.count
    assert_match(/already logged on this case/, flash[:alert])
  end

  test "case action form lists live locks with this case first" do
    case_lock = lock!(case_id: @kase.id, thread_ts: "1700000000.000200")
    unattached_lock = lock!(case_id: nil, thread_ts: "1700000000.000300")
    get fd_case_path(@kase, do: "action")
    body = response.body

    assert_operator body.index(%(value="#{case_lock.id}")), :<, body.index(%(value="#{unattached_lock.id}"))
    assert_match(/on this case/, body)
    assert_match(/on no case/, body)
  end

  test "case action form omits a done lock" do
    done_lock = lock!(state: "done", thread_ts: "1700000000.000400")
    get fd_case_path(@kase, do: "action")

    assert_no_match(/name="thread_guard_id" value="#{done_lock.id}"/, response.body)
  end

  test "case action form hides the locks target and renders targetFields and why" do
    get fd_case_path(@kase, do: "action")
    body = response.body

    assert_match(/data-action-standing-target="locks" hidden/, body)
    assert_match(/data-action-standing-target="targetFields"/, body)
    assert_match(/data-action-standing-target="why"/, body)
  end

  test "case actions tab renders On a thread and not On n/a for a lock action" do
    guard = lock!
    log(thread_guard_id: guard.id)
    get fd_case_path(@kase, tab: "actions")

    assert_match(/On a thread/, response.body)
    assert_no_match(/On n\/a/, response.body)
  end

  test "action create with a lock adds no action for target USUB" do
    guard = lock!
    log(thread_guard_id: guard.id)

    assert_empty Fd::Action.for_target(nil).where.not(case_id: nil).where(target_user_id: "USUB")
    assert_equal 0, Fd::Action.for_target("USUB").count
  end

  test "action create without roles creates no action" do
    revoke_roles!("UME")
    guard = lock!
    log(thread_guard_id: guard.id)

    assert_equal 0, actions.count
  end
end

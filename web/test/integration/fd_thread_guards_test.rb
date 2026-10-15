require "test_helper"

class FdThreadGuardsTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    @kase = make_case(subject: "USUB")
  end

  def guard!(**over)
    Fd::ThreadGuard.create!({
      kind: "lock", channel_id: "C0266FRGV", thread_ts: "1700000000.000100",
      opened_by: "UMOD", reason: "it was going nowhere", state: "running",
      expires_at: 3.days.from_now, case_id: @kase.id
    }.merge(over))
  end

  def actions_tab
    get fd_case_path(@kase, tab: "actions")
    response.body
  end

  test "a locked thread on the case is shown beside its actions" do
    guard!
    body = actions_tab

    assert_match(/Thread locked/, body)
    assert_match(/it was going nowhere/, body)
    assert_match(/running/, body)
  end

  test "a destroyed thread reads as destroyed" do
    guard!(kind: "destroy", expires_at: nil, state: "done")
    assert_match(/Thread destroyed/, actions_tab)
  end

  test "the note left in the thread is shown with the guard" do
    guard!(kind: "destroy", expires_at: nil, state: "done",
      note_rich: { "type" => "rich_text" }, note_text: "we took this down, here is why",
      note_ts: "1700000000.000200", note_posted_at: Time.current)

    assert_match(/we took this down, here is why/, actions_tab)
  end

  test "a destroy with no note says nothing extra" do
    guard!(kind: "destroy", expires_at: nil, state: "done")

    assert_no_match(/lcite/, actions_tab)
  end

  test "a guard that failed is called out" do
    guard!(state: "failed", error: "the admin account could not be invited")
    body = actions_tab
    assert_match(/failed/, body)
    assert_match(/state-crit/, body)
  end

  test "a thread guard on another case is not listed here" do
    other = make_case
    guard!(case_id: other.id)
    actions_tab
    assert_select ".thread-guard-list", false
  end

  test "a thread guard tied to no case is not listed here" do
    guard!(case_id: nil)
    actions_tab
    assert_select ".thread-guard-list", false
  end
  test "a live lock shows its time left with extend and unlock" do
    guard = guard!(expires_at: 2.hours.from_now + 5.minutes)
    body = actions_tab

    assert_match(/ends in 2h \d+m/, body)
    assert_select "form[action=?] button", fd_case_thread_lock_path(@kase, guard), text: "Unlock"
    assert_select "[data-modal-id-value=lock-extend-#{guard.id}] select[name=extend_by]"
  end

  test "a lock with no end reads as no end date" do
    guard!(expires_at: nil)

    assert_match(/no end date/, actions_tab)
  end

  test "extend adds the picked length to the current end and is audited" do
    guard = guard!
    first_end = guard.reload.expires_at

    patch fd_case_thread_lock_path(@kase, guard), params: { extend_by: "2h" }

    assert_redirected_to fd_case_path(@kase)
    assert_equal first_end + 2.hours, guard.reload.expires_at
    assert_equal "Lock extended · ends #{Fd::ShortDate.ending(first_end + 2.hours)}", flash[:notice]
    assert Fd::AuditEntry.exists?(entity_type: "thread_guard", entity_id: guard.id, verb: "extended")
  end

  test "extend with a custom end sets that end" do
    guard = guard!

    patch fd_case_thread_lock_path(@kase, guard),
      params: { extend_by: "custom", expires_on: 5.days.from_now.to_date.to_s, expires_time: "08:00" }

    assert_equal 5.days.from_now.utc.change(hour: 8, min: 0), guard.reload.expires_at
  end

  test "extend without a choice is refused" do
    guard = guard!

    patch fd_case_thread_lock_path(@kase, guard)

    assert_equal "Select how long to extend", flash[:alert]
  end

  test "unlock ends the lock and is audited" do
    guard = guard!

    delete fd_case_thread_lock_path(@kase, guard)

    assert_equal "Thread unlocked", flash[:notice]
    assert_equal "done", guard.reload.state
    assert guard.finished_at
    assert Fd::AuditEntry.exists?(entity_type: "thread_guard", entity_id: guard.id, verb: "lifted")
  end

  test "unlock on a lock that already ended is refused" do
    guard = guard!(state: "done")

    delete fd_case_thread_lock_path(@kase, guard)

    assert_equal "Lock already ended", flash[:alert]
  end

  test "somebody without thread.guard cannot unlock" do
    guard = guard!
    drop_roles!("UME")
    hold_role!("UME", "gardener")

    delete fd_case_thread_lock_path(@kase, guard)

    assert_equal "running", guard.reload.state
  end
end

require "test_helper"

class FdThreadGuardsTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
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

  test "actions tab lists lock guard with label reason and state" do
    guard!
    body = actions_tab

    assert_match(/Thread locked/, body)
    assert_match(/it was going nowhere/, body)
    assert_match(/running/, body)
  end

  test "actions tab labels destroy guard as Thread destroyed" do
    guard!(kind: "destroy", expires_at: nil, state: "done")
    assert_match(/Thread destroyed/, actions_tab)
  end

  test "actions tab shows note_text of a destroy guard" do
    guard!(kind: "destroy", expires_at: nil, state: "done",
      note_rich: { "type" => "rich_text" }, note_text: "we took this down, here is why",
      note_ts: "1700000000.000200", note_posted_at: Time.current)

    assert_match(/we took this down, here is why/, actions_tab)
  end

  test "actions tab renders no lcite for a destroy guard without note" do
    guard!(kind: "destroy", expires_at: nil, state: "done")

    assert_no_match(/lcite/, actions_tab)
  end

  test "actions tab marks a failed guard with failed text and state-crit class" do
    guard!(state: "failed", error: "the admin account could not be invited")
    body = actions_tab
    assert_match(/failed/, body)
    assert_match(/state-crit/, body)
  end

  test "actions tab omits the guard list for a guard on another case" do
    other = make_case
    guard!(case_id: other.id)
    actions_tab
    assert_select ".thread-guard-list", false
  end

  test "actions tab omits the guard list for a guard without case" do
    guard!(case_id: nil)
    actions_tab
    assert_select ".thread-guard-list", false
  end
  test "actions tab lock with future expires_at renders time left Unlock and extend select" do
    guard = guard!(expires_at: 2.hours.from_now + 5.minutes)
    body = actions_tab

    assert_match(/ends in 2h \d+m/, body)
    assert_select "form[action=?] button", fd_case_thread_lock_path(@kase, guard), text: "Unlock"
    assert_select "[data-modal-id-value=lock-extend-#{guard.id}] select[name=extend_by]"
  end

  test "actions tab lock without expires_at renders no end date" do
    guard!(expires_at: nil)

    assert_match(/no end date/, actions_tab)
  end

  test "extend adds extend_by to expires_at and writes extended audit entry" do
    guard = guard!
    first_end = guard.reload.expires_at

    patch fd_case_thread_lock_path(@kase, guard), params: { extend_by: "2h" }

    assert_redirected_to fd_case_path(@kase)
    assert_equal first_end + 2.hours, guard.reload.expires_at
    assert_equal "Lock extended · ends #{Fd::ShortDate.ending(first_end + 2.hours)}", flash[:notice]
    assert Fd::AuditEntry.exists?(entity_type: "thread_guard", entity_id: guard.id, verb: "extended")
  end

  test "extend custom sets expires_at from expires_on and expires_time" do
    guard = guard!

    patch fd_case_thread_lock_path(@kase, guard),
      params: { extend_by: "custom", expires_on: 5.days.from_now.to_date.to_s, expires_time: "08:00" }

    assert_equal 5.days.from_now.utc.change(hour: 8, min: 0), guard.reload.expires_at
  end

  test "extend without extend_by sets alert" do
    guard = guard!

    patch fd_case_thread_lock_path(@kase, guard)

    assert_equal "Select how long to extend", flash[:alert]
  end

  test "unlock marks guard done and writes lifted audit entry" do
    guard = guard!

    delete fd_case_thread_lock_path(@kase, guard)

    assert_equal "Thread unlocked", flash[:notice]
    assert_equal "done", guard.reload.state
    assert guard.finished_at
    assert Fd::AuditEntry.exists?(entity_type: "thread_guard", entity_id: guard.id, verb: "lifted")
  end

  test "unlock on a done guard sets already ended alert" do
    guard = guard!(state: "done")

    delete fd_case_thread_lock_path(@kase, guard)

    assert_equal "Lock already ended", flash[:alert]
  end

  test "unlock without thread.guard leaves state running" do
    guard = guard!
    revoke_roles!("UME")
    grant_role!("UME", "gardener")

    delete fd_case_thread_lock_path(@kase, guard)

    assert_equal "running", guard.reload.state
  end
end

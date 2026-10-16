require "test_helper"

class FdMemberStandingTest < ActionDispatch::IntegrationTest
  SUBJECT_ID = "USUB".freeze

  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def deactivation(**attrs)
    Fd::MemberGuard.create!({
      kind: "deactivation", subject_id: SUBJECT_ID, opened_by: "UFF1", reason: "raiding",
      enforced_by: "nemo", enforcement_status: "pending"
    }.merge(attrs))
  end

  test "member standing frame targets _top" do
    deactivation
    get fd_member_standing_path(SUBJECT_ID)

    assert_response :success
    assert_select %(turbo-frame#member-standing-#{SUBJECT_ID}[target="_top"])
  end

  test "member standing with pending guard renders Pending state" do
    deactivation
    get fd_member_standing_path(SUBJECT_ID)

    assert_select %(.standing-row[data-enforcement-status="pending"])
    assert_select ".enforcement-state", "Pending"
  end

  test "member standing with held guard renders Deactivated in Slack and data-landed true" do
    deactivation(enforcement_status: "held")
    get fd_member_standing_path(SUBJECT_ID)

    assert_select %(.standing-row[data-enforcement-status="held"][data-landed="true"])
    assert_select ".enforcement-state", "Deactivated in Slack"
  end

  test "member standing with held guard updated an hour ago renders data-landed false" do
    guard = deactivation(enforcement_status: "held")
    guard.update_columns(updated_at: 1.hour.ago)
    get fd_member_standing_path(SUBJECT_ID)

    assert_select %(.standing-row[data-landed="false"])
  end

  test "member standing with lifting guard renders Reactivating state" do
    deactivation(enforcement_status: "held", state: "lifting", lifted_by: "UME")
    get fd_member_standing_path(SUBJECT_ID)

    assert_select %(.standing-row[data-enforcement-status="lifting"])
    assert_select ".enforcement-state", "Reactivating"
  end

  test "member standing with failed guard renders last_error" do
    deactivation(enforcement_status: "failed", last_error: "failed: user_not_found")
    get fd_member_standing_path(SUBJECT_ID)

    assert_select %(.standing-row[data-enforcement-status="failed"])
    assert_select ".enforcement-why", "failed: user_not_found"
  end

  test "member standing with shush guard renders no enforced row or state" do
    Fd::MemberGuard.create!(kind: "shush", subject_id: SUBJECT_ID, opened_by: "UFF1",
      reason: "spam", enforced_by: "nemo", enforcement_status: "held", expires_at: 3.days.from_now)
    get fd_member_standing_path(SUBJECT_ID)

    assert_select ".standing-row.is-enforced", false
    assert_select ".enforcement-state", false
  end

  test "member standing with member.deactivate denied renders no guard lift button" do
    firefighter = grant_role!("UOBS", "firefighter")
    Authz::Override.create!(role: "firefighter", capability: "member.deactivate",
      allowed: false, changed_by: "UME")
    sign_in_as(firefighter)
    deactivation

    get fd_member_standing_path(SUBJECT_ID)
    assert_select %([data-modal-open^="guard-lift-"]), false
  end

  test "member show renders standing frame and turbo cable stream source" do
    get fd_member_path(SUBJECT_ID)

    assert_select %(turbo-frame#member-standing-#{SUBJECT_ID})
    assert_select %([data-pending-flush-frame-value="member-standing-#{SUBJECT_ID}"])
    assert_select "turbo-cable-stream-source"
  end

  test "member show renders deactivate modal with confirm-word and disabled submit" do
    get fd_member_path(SUBJECT_ID)

    assert_select %(#member-deactivate)
    assert_select %([data-controller="confirm-word"])
    assert_select %(input[data-confirm-word-target="go"][disabled])
  end

  test "member show with existing deactivation renders no deactivate modal" do
    deactivation
    get fd_member_path(SUBJECT_ID)

    assert_select %(#member-deactivate), false
  end

  def deactivate(**params)
    post fd_member_guards_path(SUBJECT_ID), params: {
      kind: "deactivation", reason: "raiding"
    }.merge(params)
  end

  test "member guards create deactivation without date has no expires_at and state live" do
    deactivate

    guard = Fd::MemberGuard.find_by(subject_id: SUBJECT_ID, kind: "deactivation")
    assert_not_nil guard
    assert_nil guard.expires_at
    assert_equal "live", guard.state
    assert_empty Fd::MemberGuard.where("expires_at IS NOT NULL"), "no guard has expires_at"
  end

  test "member guards create deactivation with expires_on sets expires_at" do
    deactivate(expires_on: "2027-01-09")

    guard = Fd::MemberGuard.find_by(subject_id: SUBJECT_ID, kind: "deactivation")
    assert_equal Date.new(2027, 1, 9), guard.expires_at.to_date
  end

  test "member guards create with invalid expires_on sets alert and creates no guard" do
    deactivate(expires_on: "the ninth")

    assert_nil Fd::MemberGuard.find_by(subject_id: SUBJECT_ID, kind: "deactivation")
    assert_match(/not a date/, flash[:alert])
  end

  test "member guards create shush without date has nil expires_at" do
    post fd_member_guards_path(SUBJECT_ID), params: { kind: "shush", reason: "spam" }

    assert_nil Fd::MemberGuard.find_by!(subject_id: SUBJECT_ID, kind: "shush").expires_at
  end

  test "member guard broadcast subject_from normalizes id and rejects blank and numeric" do
    assert_equal "USUB", Fd::MemberGuardBroadcast.subject_from("usub")
    assert_nil Fd::MemberGuardBroadcast.subject_from("")
    assert_nil Fd::MemberGuardBroadcast.subject_from("2633")
  end
end

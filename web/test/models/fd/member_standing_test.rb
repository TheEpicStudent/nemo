require "test_helper"

class Fd::MemberStandingTest < ActiveSupport::TestCase
  SUBJECT = "USTAND".freeze

  def standing(user_id = SUBJECT, at: Time.current)
    Fd::MemberStanding.new(Fd::MemberRecord.new(user_id), at: at)
  end

  def create_guard(**attrs)
    Fd::MemberGuard.create!({ kind: "shush", subject_id: SUBJECT, opened_by: "UFF1",
                              reason: "being awful", expires_at: 3.days.from_now,
                              opened_at: 2.days.ago }.merge(attrs))
  end

  def act_on(kase, **attrs)
    Fd::Action.create!({ case_id: kase.id, type_key: "warning", target_user_id: SUBJECT,
                         decided_by: "UFF1", performed_by: "UFF1",
                         performed_at: 2.days.ago }.merge(attrs))
  end

  test "standing for member with no records is clean" do
    standing_row = standing("UNOBODY")

    assert standing_row.clean?
    assert_equal 0, standing_row.priors
    assert_empty standing_row.in_force
    assert_nil standing_row.worst
    assert_nil standing_row.open_case
    assert_not standing_row.anything_in_force?
  end

  test "member who is a case subject is not clean" do
    make_case(subject: SUBJECT)
    assert_not standing.clean?
  end

  test "live guard is in force and is worst with lifts_at from expires_at" do
    create_guard

    standing_row = standing
    assert standing_row.anything_in_force?
    assert_equal 1, standing_row.in_force.size
    assert_equal "shush", standing_row.worst.kind
    assert_equal standing_row.worst.expires_at, standing_row.lifts_at
  end

  test "guard without expires_at is in force with nil lifts_at" do
    create_guard(expires_at: nil)

    standing_row = standing
    assert standing_row.anything_in_force?
    assert_nil standing_row.lifts_at
  end

  test "unexpired action alone is not in force and counts in actions" do
    kase = make_case(subject: SUBJECT)
    act_on(kase, type_key: "shush", expires_at: 3.days.from_now)

    standing_row = standing
    assert_empty standing_row.in_force, "in_force includes an action without a guard"
    assert_equal 1, standing_row.actions
  end

  test "a lifted guard is not in force" do
    create_guard(state: "lifted", lifted_at: Time.current, lifted_by: "UFF1")

    assert_empty standing.in_force
    assert_not standing.anything_in_force?
  end

  test "guard in state lifting is in force" do
    create_guard(state: "lifting", lifted_by: "UFF1")

    assert standing.anything_in_force?
  end

  test "reversed action counts in reversed and actions and is not in force" do
    kase = make_case(subject: SUBJECT)
    act_on(kase, reversed_at: Time.current, reversed_by: "UFF1", reversal_reason: "wrong person")

    standing_row = standing
    assert_empty standing_row.in_force
    assert_equal 1, standing_row.reversed
    assert_equal 1, standing_row.actions
  end

  test "worst ranks channel_ban above a newer shush and lifts_at follows it" do
    create_guard(kind: "shush", opened_at: 2.hours.ago, expires_at: 5.days.from_now)
    create_guard(kind: "channel_ban", channel_id: "C0266FRGV", opened_at: 3.days.ago,
         expires_at: 9.days.from_now)

    standing_row = standing
    assert_equal 2, standing_row.in_force.size
    assert_equal "channel_ban", standing_row.worst.kind, "a channel ban outranks a shush"
    assert_equal standing_row.worst.expires_at, standing_row.lifts_at
  end

  test "worst picks the newest of two channel_ban guards" do
    older = create_guard(kind: "channel_ban", channel_id: "COLD", opened_at: 10.days.ago)
    newer = create_guard(kind: "channel_ban", channel_id: "CNEW", opened_at: 1.day.ago)

    assert_equal newer.id, standing.worst.id
    assert_not_equal older.id, standing.worst.id
  end

  test "open_case and holder_id return the open case and its assignee" do
    kase = make_case(subject: SUBJECT, assign: "UFF1")

    standing_row = standing
    assert_equal kase.id, standing_row.open_case.id
    assert_equal "UFF1", standing_row.holder_id
  end

  test "holder_id is nil for an unassigned case" do
    make_case(subject: SUBJECT)
    assert_nil standing.holder_id
  end

  test "open_case is nil for a resolved case" do
    make_case(subject: SUBJECT, resolved_at: Time.current, resolution: "no_action")

    assert_nil standing.open_case
  end

  test "cases counts subject cases and logged_in counts cases as participant" do
    subject_case = make_case(subject: SUBJECT)
    other = make_case(subject: "USOMEBODY")
    other.participants.create!(user_id: SUBJECT, role: "reporter")

    standing_row = standing
    assert_equal 1, standing_row.cases
    assert_equal 1, standing_row.logged_in
    assert_not_equal subject_case.id, other.id
  end

  test "priors excludes cases and actions older than twelve months" do
    old = make_case(subject: SUBJECT, opened_at: 3.years.ago, resolved_at: 3.years.ago,
      resolution: "action_taken")
    act_on(old, performed_at: 3.years.ago)

    recent = make_case(subject: SUBJECT, opened_at: 2.months.ago, resolved_at: 1.month.ago,
      resolution: "action_taken")
    act_on(recent, performed_at: 2.months.ago)

    assert_equal 1, standing.priors
  end
end

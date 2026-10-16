require "test_helper"

class Fd::PriorsTest < ActiveSupport::TestCase
  SUBJECT = "UPRIOR".freeze

  def resolved_case(opened:, resolved:, resolution: "action_taken", subject: SUBJECT)
    make_case(subject: subject, opened_at: opened, resolved_at: resolved, resolution: resolution)
  end

  def act_on(kase, target: SUBJECT, **attrs)
    Fd::Action.create!({ case_id: kase.id, type_key: "warning", target_user_id: target,
                         decided_by: "UFF1", performed_by: "UFF1",
                         performed_at: kase.resolved_at || kase.opened_at }.merge(attrs))
  end

  test "prior_count counts a resolved case with an action against the subject" do
    act_on resolved_case(opened: 60.days.ago, resolved: 50.days.ago)
    assert_equal 1, Fd::Case.prior_count(SUBJECT)
  end

  test "prior_count counts an action on an open case" do
    act_on make_case(subject: SUBJECT, opened_at: 3.days.ago)
    assert_equal 1, Fd::Case.prior_count(SUBJECT),
      "a prior is an action taken against them, not a case that happens to have closed"
  end

  test "prior_count ignores an open case without an action" do
    make_case(subject: SUBJECT, opened_at: 3.days.ago)
    assert_equal 0, Fd::Case.prior_count(SUBJECT),
      "open case without an action is not a prior"
  end

  test "prior_count ignores a resolved case without an action" do
    resolved_case(opened: 60.days.ago, resolved: 50.days.ago, resolution: "no_action")
    assert_equal 0, Fd::Case.prior_count(SUBJECT)
  end

  test "prior_count ignores a case where the subject is only a reporter" do
    reporter_case = make_case(subject: "USOMEBODY", opened_at: 60.days.ago,
      resolved_at: 50.days.ago, resolution: "action_taken")
    reporter_case.participants.create!(user_id: SUBJECT, role: "reporter")
    act_on reporter_case, target: "USOMEBODY"

    assert_equal 0, Fd::Case.prior_count(SUBJECT),
      "reporter role is not a prior"
  end

  test "prior_count ignores an action targeting another user on the same case" do
    act_on resolved_case(opened: 60.days.ago, resolved: 50.days.ago), target: "UELSE"
    assert_equal 0, Fd::Case.prior_count(SUBJECT),
      "an action for another target is not a prior"
  end

  test "prior_count ignores a reversed action" do
    act_on resolved_case(opened: 60.days.ago, resolved: 50.days.ago),
      reversed_at: 40.days.ago, reversed_by: "UFF2", reversal_reason: "appeal upheld"

    assert_equal 0, Fd::Case.prior_count(SUBJECT),
      "a reversed action is not a prior"
  end

  test "prior_count counts a case with one unreversed action among reversed ones" do
    kase = resolved_case(opened: 60.days.ago, resolved: 50.days.ago)
    act_on kase, reversed_at: 40.days.ago, reversed_by: "UFF2", reversal_reason: "appeal upheld"
    act_on kase, type_key: "shush"

    assert_equal 1, Fd::Case.prior_count(SUBJECT)
  end

  test "prior_count measures within from the before time and not from now" do
    act_on resolved_case(opened: 20.months.ago, resolved: 19.months.ago)
    later_case = make_case(subject: SUBJECT, opened_at: 8.months.ago)

    assert_equal 0, Fd::Case.prior_count(SUBJECT, within: Fd::Case::PRIOR_WINDOW),
      "19 months ago is outside a year from today"
    assert_equal 1, Fd::Case.prior_count(SUBJECT, within: Fd::Case::PRIOR_WINDOW,
      before: later_case.opened_at), "19 months ago is inside a year before the later case"
  end

  test "prior_count within filters by when the action was performed" do
    act_on resolved_case(opened: 20.months.ago, resolved: 19.months.ago)
    act_on resolved_case(opened: 3.months.ago, resolved: 2.months.ago)

    assert_equal 2, Fd::Case.prior_count(SUBJECT)
    assert_equal 1, Fd::Case.prior_count(SUBJECT, within: Fd::Case::PRIOR_WINDOW)
  end

  test "prior_count with before counts only priors from before that time" do
    act_on resolved_case(opened: 60.days.ago, resolved: 50.days.ago)
    later_case = make_case(subject: SUBJECT, opened_at: 10.days.ago)

    assert_equal 1, Fd::Case.prior_count(SUBJECT, before: later_case.opened_at)
    assert_equal 0, Fd::Case.prior_count(SUBJECT, before: 55.days.ago)
  end

  test "MemberQuery summary_rows priors equals prior_count" do
    act_on resolved_case(opened: 60.days.ago, resolved: 50.days.ago)
    act_on resolved_case(opened: 20.months.ago, resolved: 19.months.ago)

    row = Fd::MemberQuery.new({}).summary_rows.find { |summary_row| summary_row.user_id == SUBJECT }
    assert_equal Fd::Case.prior_count(SUBJECT, within: Fd::Case::PRIOR_WINDOW), row.priors,
      "summary row priors match prior_count"
  end

  test "prior_count and priors_for return zero and empty for a member without actions" do
    assert_equal 0, Fd::Case.prior_count("UNOBODY")
    assert_empty Fd::Case.priors_for("UNOBODY").to_a
  end

  test "priors_for returns the ids of cases with actions" do
    first = resolved_case(opened: 60.days.ago, resolved: 50.days.ago)
    act_on first

    assert_equal [first.id], Fd::Case.priors_for(SUBJECT).ids
  end

  test "prior_count counts a case with two actions once" do
    kase = resolved_case(opened: 60.days.ago, resolved: 50.days.ago)
    act_on kase
    act_on kase, type_key: "shush"

    assert_equal 1, Fd::Case.prior_count(SUBJECT)
  end
end

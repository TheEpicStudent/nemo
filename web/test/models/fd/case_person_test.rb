require "test_helper"

class Fd::CasePersonTest < ActiveSupport::TestCase
  setup do
    @kase = make_case(subject: "UDEX", opened_at: 2.days.ago)
    @person = Fd::CasePeople.for(@kase.participants.to_a).selected
  end

  def build(actions: [], notes: [])
    Fd::CasePerson.for(@person, kase: @kase, actions: actions, notes: notes)
  end

  def action(target:, **attrs)
    Fd::Action.create!({ case_id: @kase.id, type_key: "warning", target_user_id: target,
      decided_by: "UFF1", performed_by: "UFF1", performed_at: 1.day.ago }.merge(attrs))
  end

  def note(body)
    Fd::Note.create!(case_id: @kase.id, body: body, author: "UFF1")
  end

  test "only actions aimed at this person count" do
    subject_action = action(target: "UDEX")
    action(target: "UOTHER")

    assert_equal [subject_action.id], build(actions: Fd::Action.oldest_first.to_a).actions.map(&:id)
  end

  test "a reversed action is still listed, and counted apart" do
    action(target: "UDEX", reversed_at: 1.hour.ago, reversed_by: "UFF2")
    case_person = build(actions: Fd::Action.oldest_first.to_a)

    assert_equal 1, case_person.actions.size
    assert_equal 1, case_person.reversed_actions
    assert_empty case_person.live_actions
  end

  test "priors count only cases resolved before this one opened" do
    earlier_case = make_case(subject: "UDEX", opened_at: 60.days.ago)
    earlier_case.update!(resolved_at: 50.days.ago, resolution: "action_taken")
    Fd::Action.create!(case_id: earlier_case.id, type_key: "warning", target_user_id: "UDEX",
      decided_by: "UFF1", performed_by: "UFF1", performed_at: 55.days.ago)

    later_case = make_case(subject: "UDEX", opened_at: 1.day.ago)
    later_case.update!(resolved_at: Time.current, resolution: "action_taken")
    Fd::Action.create!(case_id: later_case.id, type_key: "warning", target_user_id: "UDEX",
      decided_by: "UFF1", performed_by: "UFF1", performed_at: 1.hour.ago)

    assert_equal 1, build.priors, "a case resolved after this one opened is not a prior for it"
  end

  test "the rows explain themselves, and agree with the count" do
    prior_case = make_case(subject: "UDEX", opened_at: 60.days.ago)
    prior_case.update!(resolved_at: 50.days.ago, resolution: "action_taken")
    action(target: "UDEX", case_id: prior_case.id, performed_at: 55.days.ago)

    reversed_case = make_case(subject: "UDEX", opened_at: 40.days.ago)
    reversed_case.update!(resolved_at: 30.days.ago, resolution: "action_taken")
    action(target: "UDEX", case_id: reversed_case.id, performed_at: 35.days.ago,
      reversed_at: 20.days.ago, reversed_by: "UFF2", reversal_reason: "appeal upheld")

    no_action_case = make_case(subject: "UDEX", opened_at: 20.days.ago)
    no_action_case.update!(resolved_at: 10.days.ago, resolution: "no_action")

    reporter_case = make_case(subject: "USOMEBODY", opened_at: 15.days.ago)
    reporter_case.update!(resolved_at: 12.days.ago, resolution: "action_taken")
    Fd::CaseParticipant.create!(case_id: reporter_case.id, user_id: "UDEX", role: "reporter")
    action(target: "USOMEBODY", case_id: reporter_case.id, performed_at: 13.days.ago)

    case_person = build
    reasons = case_person.earlier_cases.to_h { |row| [row.kase.id, row.reason] }

    assert_nil reasons[prior_case.id]
    assert_equal "the action was reversed", reasons[reversed_case.id]
    assert_equal "nothing was done to them", reasons[no_action_case.id]
    assert_equal "logged, not the subject", reasons[reporter_case.id]
    assert_equal case_person.priors, case_person.earlier_cases.count(&:counts),
      "the number and the rows behind it must never disagree"
  end

  MessageRow = Struct.new(:channel_id, :thread_ts, :author_user_id, keyword_init: true)

  test "only their own messages land in their pane" do
    subject_message = MessageRow.new(channel_id: "C0LOUNGE", thread_ts: "1.1", author_user_id: "UDEX")
    other_message = MessageRow.new(channel_id: "C0LOUNGE", thread_ts: "1.1", author_user_id: "UELSE")
    case_person = Fd::CasePerson.for(@person, kase: @kase, actions: [], notes: [],
      messages: [subject_message, other_message])

    assert_equal [subject_message], case_person.messages
  end

  test "speaking twice in one thread is one thread, not two" do
    shares = Array.new(2) do |i|
      MessageRow.new(channel_id: "C0LOUNGE", thread_ts: "1.1", author_user_id: "UDEX")
    end
    shares << MessageRow.new(channel_id: "C0SHIP", thread_ts: "2.2", author_user_id: "UDEX")
    case_person = Fd::CasePerson.for(@person, kase: @kase, actions: [], notes: [], messages: shares)

    assert_equal 3, case_person.messages.size
    assert_equal 2, case_person.threads_spoken_in
  end

  test "cases ever counts every case they appear on, in any role" do
    other = make_case(subject: "USOMEBODY")
    Fd::CaseParticipant.create!(case_id: other.id, user_id: "UDEX", role: "reporter")

    assert_equal 2, build.cases_ever
  end
end

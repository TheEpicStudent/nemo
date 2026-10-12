require "test_helper"

class FdMergedCaseTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    @root = make_case(subject: "USUB", opened_at: 10.days.ago)
    @duplicate = make_case(subject: "USUB", opened_at: 4.days.ago)
    @duplicate.update!(resolved_at: 2.days.ago, resolution: "duplicate", duplicate_of: @root.id)
  end

  def act_on(kase, **attrs)
    Fd::Action.create!({ case_id: kase.id, type_key: "warning", target_user_id: "USUB",
                         decided_by: "UFF1", performed_by: "UFF1",
                         performed_at: 1.day.ago }.merge(attrs))
  end

  test "a case with nothing merged into it is unchanged" do
    unmerged = make_case(subject: "UOTHER", opened_at: 3.days.ago)
    act_on(unmerged)

    get fd_case_path(unmerged)
    assert_response :success
  end

  def report_on(kase, reporter_id, at:)
    report = Fd::CaseReport.create!(case_id: kase.id, reporter_user_id: reporter_id,
      is_anonymous: false, body: "#{reporter_id} said something", source_app: "relay", received_at: at)
    Fd::IntakeConversation.create!(report_id: report.id, member_user_id: reporter_id,
      channel_id: "D0#{reporter_id}", thread_ts: "1700.#{report.id}", opened_at: at)
    report
  end

  test "a reply goes to the thread you were reading, not the first one" do
    people = Fd::Member.order(:user_id).limit(2).pluck(:user_id)
    report_on(@root, people.first, at: 3.days.ago)
    duplicate_report = report_on(@duplicate, people.last, at: 6.days.ago)
    conversation = Fd::IntakeConversation.find_by(report_id: duplicate_report.id)

    post fd_case_replies_path(@root), params: { body: "we are on it",
      conversation_id: conversation.id }, as: :turbo_stream

    assert_equal conversation.id, Fd::IntakeOutbox.sole.conversation_id
  end

  def resolved_count
    Fd::CaseQuery.view_counts(nil)["resolved"]
  end

  test "the queue does not count a folded case as resolved work" do
    get fd_cases_path(view: "resolved")

    resolved_before = resolved_count
    @duplicate.update!(duplicate_of: nil)

    assert_equal resolved_count - 1, resolved_before, "a merge is filing, not an outcome"
  end

  test "a merge counts as neither a resolution nor a time to resolve" do
    start = Time.current.beginning_of_month
    @duplicate.update!(opened_at: start + 1.minute, resolved_at: start + 2.minutes)
    stats_with_merge = Fd::QueueStats.load
    @duplicate.update!(duplicate_of: nil)
    stats_without_merge = Fd::QueueStats.load

    assert_equal stats_without_merge.opened_month_resolved - 1, stats_with_merge.opened_month_resolved
    assert_not_equal stats_without_merge.median_now, stats_with_merge.median_now
    assert_equal stats_without_merge.total, stats_with_merge.total, "it is still a case that happened"
  end

  test "a case resolved on its own merits still counts" do
    resolved_before = resolved_count
    @duplicate.update!(resolution: "no_action", duplicate_of: nil)

    assert_equal resolved_before + 1, resolved_count
  end
end

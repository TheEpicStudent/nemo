require "test_helper"

class FdOpenCaseTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    @watermark = Fd::Case.maximum(:id).to_i
  end

  def open_case(**params)
    post fd_cases_path, params: { subject_user_id: "USUB", body: "saw it live" }.merge(params)
  end

  def opened
    Fd::Case.where("id > ?", @watermark).where(opened_by: @me.user_id).order(:id).last
  end

  test "a signed out visitor cannot open a case" do
    open_case
    assert_redirected_to login_path
    assert_nil opened
  end

  test "the queue carries the form in a modal, closed by default" do
    sign_in_as(@me)
    get fd_cases_path

    assert_response :success
  end

  test "opening records who opened it and when" do
    sign_in_as(@me)
    open_case(category_key: "bullying")

    kase = opened
    assert_equal "USUB", kase.subject_user_id
    assert_equal "bullying", kase.category_key
    assert_equal "UME", kase.opened_by
    assert_equal "fire_engine", kase.source_app
    assert_redirected_to fd_case_path(kase)
  end

  test "it joins the queue unassigned by default" do
    sign_in_as(@me)
    open_case
    assert_not opened.assigned?
  end

  test "it can be assigned to me as it opens" do
    sign_in_as(@me)
    open_case(assign_to_me: "1")

    assert_equal ["UME"], opened.assignee_user_ids
    assert_equal "UME", opened.assignees.sole.assigned_by
  end

  test "a case can be opened with nobody identified as the subject yet" do
    sign_in_as(@me)
    open_case(subject_user_id: "  ")

    kase = opened
    assert_not_nil kase
    assert_empty kase.subject_user_ids
    assert_redirected_to fd_case_path(kase)
  end

  test "a category outside the list is refused" do
    sign_in_as(@me)
    open_case(category_key: "vibes")

    assert_nil opened
    assert_match(/pick a category from the list/, flash[:alert])
  end

  test "no category at all is allowed" do
    sign_in_as(@me)
    open_case(category_key: "")
    assert_nil opened.category_key
  end

  test "what happened is the case's first message, not a note" do
    sign_in_as(@me)
    open_case(body: "saw this live in the lounge")

    first = Fd::CaseChat.where(case_id: opened.id).sole
    assert_equal "saw this live in the lounge", first.body
    assert_equal "UME", first.author_user_id
    assert_equal "card", first.mirrored_as
    assert_equal 0, opened.notes.count
  end

  test "a case with nothing said about what happened is refused" do
    sign_in_as(@me)
    open_case(body: "  ")

    assert_nil opened
    assert_match(/say what happened/, flash[:alert])
  end

  test "a posted thread link is ignored" do
    sign_in_as(@me)
    open_case(link: "https://hackclub.slack.com/archives/C0266FRGV/p1754487721123456")

    assert_not_nil opened
    assert_equal 0, opened.threads.count, "the form does not take a thread, so none is attached"
  end

  test "a case opens with a subject and what happened" do
    sign_in_as(@me)
    open_case

    assert_not_nil opened
    assert_equal 0, opened.threads.count
    assert_equal 0, opened.notes.count
  end

  test "what happened stays out of the trail" do
    sign_in_as(@me)
    open_case(body: "he mentioned self harm")

    entries = Fd::AuditEntry.where(request_id: Fd::AuditEntry
      .where(entity_type: "case", entity_id: opened.id, verb: "opened").select(:request_id))
    assert_no_match(/self harm/, entries.map { |entry| entry.after.to_json }.join)
  end

  test "a case can be opened about several people at once" do
    sign_in_as(@me)
    post fd_cases_path, params: { subject_user_ids: %w[UONE UTWO UTHREE], body: "saw it live" }

    kase = Fd::Case.order(:id).last
    assert_equal %w[UONE UTHREE UTWO], kase.subject_user_ids
    assert_match(/opened, about 3 people/, flash[:notice])
  end

  test "each subject gets its own trail entry, under the one request" do
    sign_in_as(@me)
    post fd_cases_path, params: { subject_user_ids: %w[UONE UTWO], body: "saw it live" }

    kase = Fd::Case.order(:id).last
    rows = Fd::AuditEntry.where(entity_type: "participant", entity_id: kase.id, verb: "attached")
    assert_equal 2, rows.count
    assert_equal %w[UONE UTWO], rows.map { |row| row.after["user_id"] }.sort
    assert_equal 1, rows.pluck(:request_id).uniq.size
  end

  test "one bad id refuses the whole case rather than opening a half one" do
    sign_in_as(@me)
    before = Fd::Case.count
    post fd_cases_path, params: { subject_user_ids: %w[UONE bob], body: "saw it live" }

    assert_equal before, Fd::Case.count
    assert_match(/does not look like a Slack member id/, flash[:alert])
  end

  test "the same person named twice is one subject, not two" do
    sign_in_as(@me)
    post fd_cases_path, params: { subject_user_ids: %w[UONE UONE], body: "saw it live" }

    assert_equal ["UONE"], Fd::Case.order(:id).last.subject_user_ids
  end

  test "an open case for any of the people named does not stop the submit" do
    make_case(subject: "UTWO", opened_at: 3.days.ago)
    sign_in_as(@me)
    post fd_cases_path, params: { subject_user_ids: %w[UONE UTWO], body: "saw it live" }

    assert_not_nil opened
    assert_nil flash[:alert]
    assert_redirected_to fd_case_path(opened)
  end

  test "a subject with an open case opens a second one on the first submit" do
    make_case(opened_at: 3.days.ago, category_key: "bullying")
    sign_in_as(@me)
    open_case

    assert_not_nil opened
    assert_equal "USUB", opened.subject_user_id
    assert_equal 2, Fd::Case.unresolved.with_subject("USUB").count
  end

  test "a resolved case for the same subject is no obstacle either" do
    make_case(opened_at: 5.days.ago, resolved_at: 1.day.ago, resolution: "no_action")
    sign_in_as(@me)
    open_case

    assert_not_nil opened, "a closed case is not a reason to stop"
  end

  test "somebody else's open case is not a reason to stop" do
    make_case(subject: "UELSE", opened_at: 3.days.ago)
    sign_in_as(@me)
    open_case

    assert_not_nil opened
  end

  test "unticking it still opens the case unassigned" do
    sign_in_as(@me)
    post fd_cases_path, params: { subject_user_ids: ["USUB"], body: "said it again",
                                  assign_to_me: "0" }

    assert_empty Fd::Case.order(:id).last.assignees,
      "an explicit untick must not be overridden by the default"
  end
end

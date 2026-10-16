require "test_helper"

class FdMemberRecordTest < ActionDispatch::IntegrationTest
  SUBJECT = "UPRIOR".freeze

  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def act_on(kase, target: SUBJECT, **attrs)
    Fd::Action.create!({ case_id: kase.id, type_key: "warning", target_user_id: target,
                         decided_by: "UFF1", performed_by: "UFF1" }.merge(attrs))
  end

  test "a member with nothing on them still gets a page" do
    get fd_member_path("UNOBODY")

    assert_response :success
  end

  test "the priors format_number uses the definition, not the case count" do
    action_taken_case = make_case(subject: SUBJECT, opened_at: 40.days.ago, resolved_at: 30.days.ago,
      resolution: "action_taken")
    act_on action_taken_case
    make_case(subject: SUBJECT, opened_at: 20.days.ago, resolved_at: 10.days.ago,
      resolution: "no_action")
    make_case(subject: SUBJECT, opened_at: 2.days.ago)

    assert_equal 1, Fd::Case.prior_count(SUBJECT, within: Fd::Case::PRIOR_WINDOW)
  end

  test "looking at a member writes an access log row against me" do
    before = AccessLog.count
    get fd_member_path(SUBJECT)

    assert_equal before + 1, AccessLog.count
    entry = AccessLog.order(:id).last
    assert_equal "UME", entry.actor_id
    assert_equal SUBJECT, entry.subject_user_id
  end

  test "a signed out visitor sees nothing and logs nothing" do
    delete logout_path
    before = AccessLog.count
    get fd_member_path(SUBJECT)

    assert_redirected_to login_path
    assert_equal before, AccessLog.count, "a refused request must not record a lookup"
  end

  test "a note written here follows the member rather than a case" do
    post fd_member_notes_path(SUBJECT), params: { body: "escalates in public" }

    note = Fd::Note.for_subject(SUBJECT).sole
    assert_nil note.case_id, "a standing note belongs to the member, not a case"
    assert_equal "UME", note.author
    assert_match(/follows them to every case/, flash[:notice])
    assert_redirected_to fd_member_path(SUBJECT)
  end

  test "an empty note is refused here too" do
    post fd_member_notes_path(SUBJECT), params: { body: "   " }

    assert_empty Fd::Note.for_subject(SUBJECT).to_a
    assert_nil flash[:alert], "a problem with one field is not a page-level message"
    assert_equal "body", flash[:field_error]["field"]
    assert_match(/Write the note/i, flash[:field_error]["message"])
    assert_redirected_to fd_member_path(SUBJECT)
  end

  test "the note text never reaches the trail, only its length" do
    post fd_member_notes_path(SUBJECT), params: { body: "he mentioned self harm" }

    entry = Fd::AuditEntry.where(entity_type: "note", verb: "noted").order(:id).last
    assert_equal "redacted, 22 chars", entry.after["body"]
    assert_no_match(/self harm/, entry.after.to_json)
  end

  test "member note remove works on notes by other authors" do
    post fd_member_notes_path(SUBJECT), params: { body: "mine to remove" }
    own_note = Fd::Note.for_subject(SUBJECT).sole
    other_note = Fd::Note.create!(subject_user_id: SUBJECT, body: "not mine", author: "UFF9")

    delete fd_member_note_path(SUBJECT, other_note)
    assert_not_nil other_note.reload.deleted_at
    assert_equal "Note removed", flash[:notice]

    delete fd_member_note_path(SUBJECT, own_note)
    assert_not_nil own_note.reload.deleted_at
  end

  test "member note update edits the body and marks it edited" do
    note = Fd::Note.create!(subject_user_id: SUBJECT, body: "spoke to tehm", author: "UFF9")

    patch fd_member_note_path(SUBJECT, note), params: { body: "spoke to them @U0ABCDEF12" }

    assert_redirected_to fd_member_path(SUBJECT)
    assert_equal "Note updated", flash[:notice]
    note.reload
    assert_equal "spoke to them <@U0ABCDEF12>", note.body
    assert_equal "UFF9", note.author
    assert note.edited?
    entry = Fd::AuditEntry.where(entity_type: "note", entity_id: note.id, verb: "edited").sole
    assert_no_match(/spoke to/, entry.to_json)
  end

  test "member note update with blank body reopens the edit modal" do
    note = Fd::Note.create!(subject_user_id: SUBJECT, body: "keep", author: "UFF9")

    patch fd_member_note_path(SUBJECT, note), params: { body: " " }

    assert_redirected_to fd_member_path(SUBJECT, do: "edit-note-#{note.id}")
    assert_equal "Enter the note", flash[:field_error]["message"]
    assert_equal "keep", note.reload.body
  end

  test "member history shows edit and remove on standing notes by other authors" do
    note = Fd::Note.create!(subject_user_id: SUBJECT, body: "not mine", author: "UFF9")

    get fd_member_path(SUBJECT)

    assert_select "button[data-modal-open='edit-note-#{note.id}']", text: "Edit"
    assert_select "form[action='#{fd_member_note_path(SUBJECT, note)}'] button", text: "Remove"
    assert_select "[data-modal-id-value='edit-note-#{note.id}'] textarea[name='body']", text: "not mine"
  end

  test "member note update on another member is not found" do
    note = Fd::Note.create!(subject_user_id: "UOTHER99", body: "keep", author: "UFF9")

    patch fd_member_note_path(SUBJECT, note), params: { body: "changed" }

    assert_equal "Note not found", flash[:alert]
    assert_equal "keep", note.reload.body
  end
end

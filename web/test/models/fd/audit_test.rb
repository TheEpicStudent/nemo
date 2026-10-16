require "test_helper"

class Fd::AuditTest < ActiveSupport::TestCase
  def kase(**attrs)
    make_case(opened_at: Time.current, **attrs)
  end

  def record(target, verb, **opts)
    Fd::Audit.record(target, verb, **{ actor: "UFF1" }.merge(opts))
  end

  test "entity_type maps each conduct model to its entity type" do
    assert_equal "case", Fd::Audit.entity_type(Fd::Case.new)
    assert_equal "action", Fd::Audit.entity_type(Fd::Action.new)
    assert_equal "note", Fd::Audit.entity_type(Fd::Note.new)
    assert_equal "report", Fd::Audit.entity_type(Fd::CaseReport.new)
    assert_equal "thread", Fd::Audit.entity_type(Fd::CaseThread.new)
    assert_equal "participant", Fd::Audit.entity_type(Fd::CaseParticipant.new)
  end

  test "entity_type raises UnauditableRecordError for a model outside the conduct schema" do
    assert_raises(Fd::Audit::UnauditableRecordError) { Fd::Audit.entity_type(Account.new) }
  end

  test "record raises UnknownVerbError for an unknown verb" do
    assert_raises(Fd::Audit::UnknownVerbError) { record(kase, "yeeted") }
  end

  test "record for a new row has nil before and an after with opened_by" do
    entry = record(kase, "opened")
    assert_nil entry.before
    assert_equal "UFF1", entry.after["opened_by"]
  end

  test "record with entity_id stores it on a participant entry" do
    target = kase
    person = target.add_subject!("UANOTHER")
    entry = record(person, "attached", entity_id: target.id)

    assert_equal "participant", entry.entity_type
    assert_equal target.id, entry.entity_id
    assert_equal "UANOTHER", entry.after["user_id"]
    assert_equal "subject", entry.after["role"]
  end

  test "record for a new row includes columns equal to their database default" do
    thread = Fd::CaseThread.create!(case_id: kase.id, channel_id: "C1", thread_ts: "1.1",
      added_by: "UFF1")
    entry = record(thread, "attached")

    assert_equal "evidence", entry.after["kind"],
      "column with its default value is included in after"
    assert_equal "C1", entry.after["channel_id"]
    assert_equal false, entry.after["is_primary"]
  end

  test "record for a new row omits nil columns" do
    entry = record(kase, "opened")
    assert_not entry.after.key?("resolution")
    assert_not entry.after.key?("category_key")
  end

  test "record after an update stores only changed columns in before and after" do
    target = kase
    target.update!(category_key: "bullying")
    entry = record(target, "opened")
    assert_equal({ "category_key" => nil }, entry.before.slice("category_key"))
    assert_equal "bullying", entry.after["category_key"]
    assert_not entry.after.key?("opened_by")
  end

  test "record omits IGNORED_COLUMNS from after" do
    target = kase
    target.update!(category_key: "bullying")
    entry = record(target, "opened")
    assert_empty entry.after.keys & Fd::Audit::IGNORED_COLUMNS
  end

  test "record redacts a note body to a character count" do
    note = Fd::Note.create!(case_id: kase.id, body: "he apologised in DM", author: "UFF1")
    entry = record(note, "noted")
    assert_equal "redacted, 19 chars", entry.after["body"]
    assert_no_match(/apologised/, entry.after.to_json)
  end

  test "record redacts member_note to a character count" do
    target = kase
    target.update!(resolved_at: Time.current, resolution: "action_taken", member_note: "we spoke")
    entry = record(target, "resolved")
    assert_equal "redacted, 8 chars", entry.after["member_note"]
    assert_equal "action_taken", entry.after["resolution"]
  end

  test "record for a soft deleted note omits body" do
    note = Fd::Note.create!(case_id: kase.id, body: "x", author: "UFF1")
    note.update!(deleted_at: Time.current, deleted_by: "UFF1")
    entry = record(note, "deleted")
    assert_not entry.after.key?("body")
  end

  test "record with explicit before and after uses them" do
    target = kase
    entry = record(target, "resolved",
      before: { "resolution" => nil }, after: { "resolution" => "no_action" })
    assert_equal "no_action", entry.after["resolution"]
  end

  test "record stores actor_user_id with request_id and source_app" do
    entry = record(kase, "opened", actor: "UFF7", request_id: "req-123")
    assert_equal "UFF7", entry.actor_user_id
    assert_equal "human", entry.actor_kind
    assert_equal "req-123", entry.request_id
    assert_equal "fire_engine", entry.source_app
  end

  test "record with the same request_id stores entries sharing it" do
    target = kase
    record(target, "opened", request_id: "req-9")
    record(target, "claimed", request_id: "req-9")
    assert_equal 2, Fd::AuditEntry.where(request_id: "req-9").count
  end

  test "audit entry update and destroy raise ReadOnlyRecord" do
    entry = record(kase, "opened")
    assert_raises(ActiveRecord::ReadOnlyRecord) { entry.update!(verb: "resolved") }
    assert_raises(ActiveRecord::ReadOnlyRecord) { entry.destroy }
  end
end

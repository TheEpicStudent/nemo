require "test_helper"

class Fd::AuditTrailTest < ActiveSupport::TestCase
  ACTOR_ID = "UFF1".freeze

  def audit(entity_type, entity_id, verb, at: 1.hour.ago, actor: ACTOR_ID, after: nil)
    Fd::AuditEntry.create!(actor_user_id: actor, actor_kind: "human", entity_type: entity_type,
      entity_id: entity_id, verb: verb, source_app: "fire_engine", occurred_at: at,
      after: after)
  end

  def audit_rows(only: nil, **opts)
    Fd::AuditTrail.new(ACTOR_ID, since: 30.days.ago, only: only, **opts).rows
  end

  test "case entity row links to the case" do
    kase = make_case
    audit("case", kase.id, "resolved")

    row = audit_rows.sole
    assert_equal "case/resolved", row.event
    assert_equal ["case", kase.id, "case #{kase.id}"], [row.kind, row.id, row.about]
  end

  test "action entity row links to the case with type as detail and target as who" do
    kase = make_case
    action = Fd::Action.create!(case_id: kase.id, type_key: "temp_ban",
      target_user_id: "USUB", decided_by: ACTOR_ID, performed_by: ACTOR_ID)
    audit("action", action.id, "performed")

    row = audit_rows.sole
    assert_equal ["case", kase.id], [row.kind, row.id]
    assert_equal ["temp ban", "USUB"], [row.detail, row.who]
  end

  test "note entity row with subject_user_id links to the member" do
    note = Fd::Note.create!(subject_user_id: "USUB", body: "keep an eye", author: ACTOR_ID)
    audit("note", note.id, "noted")

    row = audit_rows.sole
    assert_equal ["member", "USUB"], [row.kind, row.id]
  end

  test "case child entity rows link to the case id" do
    kase = make_case
    %w[participant thread citation assignee].each { |type| audit(type, kase.id, "attached") }

    assert_equal [kase.id] * 4, audit_rows.map(&:id)
    assert_equal ["case"] * 4, audit_rows.map(&:kind)
  end

  test "capability_grant row links to the member with role as detail" do
    grant = Authz::Grant.grant!("UNEW", kind: "role", name: "firefighter", by: ACTOR_ID)
    audit("capability_grant", grant.id, "granted",
      after: { "user_id" => "UNEW", "role" => "firefighter" })

    row = audit_rows.sole
    assert_equal ["member", "UNEW", "firefighter"], [row.kind, row.id, row.detail]
  end

  test "rows with only keeps events covered by the permission" do
    kase = make_case
    action = Fd::Action.create!(case_id: kase.id, type_key: "warning", target_user_id: "USUB",
      decided_by: ACTOR_ID, performed_by: ACTOR_ID)
    audit("action", action.id, "performed")
    audit("case", kase.id, "opened")

    assert_equal ["action/performed"], audit_rows(only: "case.act").map(&:event)
    assert_equal ["case/opened"], audit_rows(only: "case.open").map(&:event)
  end

  test "rows with only case.read returns no rows" do
    audit("case", make_case.id, "opened")

    assert_empty audit_rows(only: "case.read")
  end

  test "rows with only identity.read come from AccessLog" do
    audit("case", make_case.id, "opened")
    AccessLog.create!(actor_id: ACTOR_ID, subject_user_id: "USUB", field_class: "identity",
      looked_at: 2.days.ago)

    row = audit_rows(only: "identity.read").sole
    assert_equal ["identity/read", "member", "USUB"], [row.event, row.kind, row.id]
  end

  test "rows exclude refused entries" do
    audit("case", 0, "refused")

    assert_empty audit_rows
  end

  test "rows exclude other actors and entries older than since" do
    kase = make_case
    audit("case", kase.id, "opened", actor: "UOTHER")
    audit("case", kase.id, "reopened", at: 2.months.ago)

    assert_empty audit_rows
  end

  test "rows orders by occurred_at desc and honors limit" do
    kase = make_case
    audit("case", kase.id, "opened", at: 3.days.ago)
    audit("case", kase.id, "claimed", at: 1.day.ago)
    audit("case", kase.id, "resolved", at: 2.hours.ago)

    assert_equal %w[case/resolved case/claimed], audit_rows(limit: 2).map(&:event)
  end

  test "member_ids returns action target with note subject and actor" do
    kase = make_case
    action = Fd::Action.create!(case_id: kase.id, type_key: "warning", target_user_id: "USUB",
      decided_by: ACTOR_ID, performed_by: ACTOR_ID)
    audit("action", action.id, "performed")
    note = Fd::Note.create!(subject_user_id: "UWATCHED", body: "keep an eye", author: ACTOR_ID)
    audit("note", note.id, "noted")

    assert_equal ["UWATCHED", "USUB", ACTOR_ID].sort,
      Fd::AuditTrail.new(ACTOR_ID, since: 30.days.ago).member_ids.sort,
      "member_ids includes the actor id"
  end
end

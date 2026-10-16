require "test_helper"

class Fd::MemberIdentityTest < ActiveSupport::TestCase
  setup do
    @me = grant_role!("UME", "community_manager")
  end

  test "fd.member and fd.member_identity have no write grant for the app" do
    assert_read_only! "fd.member"
    assert_read_only! "fd.member_identity"
  end

  test "persisted Member and MemberIdentity rows are readonly" do
    assert Fd::Member.new(user_id: "U1").tap { |row| row.instance_variable_set(:@new_record, false) }
      .readonly?
    assert Fd::MemberIdentity.new(user_id: "U1")
      .tap { |row| row.instance_variable_set(:@new_record, false) }.readonly?
  end

  test "look_up without an actor raises NoActorError" do
    assert_raises(Fd::MemberIdentity::NoActorError) do
      Fd::MemberIdentity.look_up("UMEMBER", actor: nil)
    end
  end

  test "look_up of an unknown member returns nil and logs an access" do
    before = AccessLog.count
    assert_nil Fd::MemberIdentity.look_up("UNOBODY", actor: @me)

    entry = AccessLog.order(:id).last
    assert_equal before + 1, AccessLog.count
    assert_equal "UME", entry.actor_id
    assert_equal "UNOBODY", entry.subject_user_id
    assert_equal "identity", entry.field_class
  end

  test "look_up without identity.read returns a refused row and logs nothing" do
    firefighter = Account.create!(user_id: "UFF1")
    grant_role!("UFF1", "firefighter")
    override_capability!("firefighter", "identity.read", false, by: "UME")
    before = AccessLog.count

    row = Fd::MemberIdentity.look_up(Fd::Member.order(:user_id).first.user_id, actor: firefighter)

    assert row.refused?
    assert_nil row.email
    assert_equal before, AccessLog.count, "a read that did not happen must not be logged"
  end

  test "a read that is allowed is not marked refused" do
    assert_not Fd::MemberIdentity.look_up("UNOBODY", actor: @me)&.refused?
    assert_not Fd::MemberIdentity.look_up(Fd::Member.order(:user_id).first.user_id,
      actor: @me).refused?
  end

  test "audit redacts every member_identity column and maps the entity type" do
    assert_equal %w[real_name first_name last_name email],
      Fd::Audit::REDACTED_COLUMNS.fetch("identity")
    assert_equal "identity", Fd::Audit.entity_type(Fd::MemberIdentity.new)
  end

  test "member_identity has no phone column" do
    assert_not Fd::MemberIdentity.column_names.include?("phone")
  end

  test "Member#name falls back from display name to handle to user id" do
    assert_equal "Ada", Fd::Member.new(display_name: "Ada", handle: "ada").name
    assert_equal "ada", Fd::Member.new(display_name: "", handle: "ada").name
    assert_equal "@UBARE", Fd::Member.new(user_id: "UBARE").name
  end

  test "member has none of the identity columns" do
    assert_not Fd::Member.column_names.intersect?(%w[real_name first_name last_name email])
  end

  test "look_up of a seeded member returns the identity and logs an access" do
    seeded = Fd::Member.order(:user_id).first
    before = AccessLog.count

    row = Fd::MemberIdentity.look_up(seeded.user_id, actor: @me)

    assert_equal seeded.user_id, row.user_id
    assert_match(/\A\w+ \w+\z/, row.real_name)
    assert_equal before + 1, AccessLog.count
    assert_equal seeded.user_id, AccessLog.order(:id).last.subject_user_id
  end

  test "seeded identities use only example.invalid emails" do
    assert_equal 0, Fd::MemberIdentity.where.not(email: nil)
      .where.not("email LIKE '%@example.invalid'").count
  end

  test "every seeded member has an identity with a handle based email" do
    assert_equal Fd::Member.count, Fd::MemberIdentity.count
    assert_equal 0, Fd::Member.joins(:identity)
      .where.not("fd.member_identity.email = fd.member.handle || '@example.invalid'").count
  end

  test "seeded members include some with a blank display name" do
    assert_operator Fd::Member.where(display_name: "").count, :>, 0
  end
end

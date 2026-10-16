require "test_helper"

class FdGrantsTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def post_grant(user_id: "U0AFF1", role: "firefighter", **extra_params)
    post admin_grants_path, params: { user_id: user_id, role: role }.merge(extra_params)
    Current.forget_roles
  end

  def role_grant(user_id = "U0AFF1")
    Current.forget_roles
    Authz::Grant.live.roles.find_by(user_id: user_id)
  end

  test "grants create records the role and granted_by with a granted audit entry" do
    post_grant

    grant = role_grant
    assert_equal "firefighter", grant.name
    assert_equal "UME", grant.granted_by
    assert_redirected_to admin_person_path("U0AFF1")
    assert Fd::AuditEntry.exists?(entity_type: "capability_grant", entity_id: grant.id,
      verb: "granted")
  end

  test "grants create with blank or malformed user_id alerts and creates no grant" do
    post_grant(user_id: "")
    assert_match(/Select a member/, flash[:alert])

    post_grant(user_id: "not-an-id")
    assert_match(/is not a Slack user id/, flash[:alert])

    assert_equal 0, Authz::Grant.for_person("U0AFF1").count
  end

  test "grants create with a new role revokes the old grant and adds one" do
    post_grant
    post_grant(role: "gardener")

    assert_equal "gardener", role_grant.name
    assert_equal 2, Authz::Grant.for_person("U0AFF1").roles.count
    assert_equal 1, Authz::Grant.for_person("U0AFF1").roles.where.not(revoked_at: nil).count
  end

  test "grants destroy revokes the role grant and sets revoked_by" do
    post_grant
    grant = role_grant

    delete admin_grant_path("U0AFF1")

    assert_nil role_grant
    assert_equal "UME", grant.reload.revoked_by
  end

  test "grants create without role revokes the role grant and writes a revoked audit entry" do
    post_grant
    grant = role_grant

    post admin_grants_path, params: { user_id: "U0AFF1" }

    assert_nil role_grant
    assert Fd::AuditEntry.exists?(entity_type: "capability_grant", entity_id: grant.id,
      verb: "revoked")
  end

  test "grants destroy of the last manager alerts and keeps manager?" do
    delete admin_grant_path("UME")

    assert_match(/Cannot revoke own access/, flash[:alert])
    assert_predicate Account.find("UME"), :manager?
  end

  test "grants create as firefighter creates no grant and redirects to root" do
    delete logout_path
    firefighter = Account.create!(user_id: "ULEAD")
    Authz::Grant.grant!("ULEAD", kind: "role", name: "firefighter", by: "UME")
    Current.forget_roles
    sign_in_as(firefighter)

    post_grant

    assert_nil role_grant
    assert_redirected_to root_path
  end

  test "grants create community_manager revokes the old role and writes a granted audit entry" do
    post_grant
    post admin_grants_path, params: { user_id: "U0AFF1", role: "community_manager" }
    Current.forget_roles

    assert_predicate Account.find("U0AFF1"), :manager?
    assert_equal "community_manager", role_grant.name
    assert_equal 1, Authz::Grant.for_person("U0AFF1").roles.where.not(revoked_at: nil).count
    assert Fd::AuditEntry.where(verb: "granted")
      .any? { |row| row.after&.dig("role") == "community_manager" }
  end

  test "admin people as firefighter redirects to root" do
    Authz::Grant.grant!("U0AFF1", kind: "role", name: "firefighter", by: "UME")

    get admin_people_path

    get admin_person_path("U0AFF1")

    delete logout_path
    lead = Account.create!(user_id: "ULEAD")
    Authz::Grant.grant!("ULEAD", kind: "role", name: "firefighter", by: "UME")
    sign_in_as(lead)

    get admin_people_path
    assert_redirected_to root_path, "the admin section is managers only"
  end

  test "admin people renders the give access combo outside a label" do
    get admin_people_path

    assert_select %(#give-access-form .combo[data-combobox-name-value="user_id"])
    assert_select "#give-access-form label .combo", count: 0
  end

  test "grants create stores reason" do
    post_grant(reason: "covering the weekend")

    assert_equal "covering the weekend", role_grant.reason
  end

  test "grants create without reason stores nil reason" do
    post_grant

    grant = role_grant
    assert_nil grant.reason
    assert_equal "firefighter", grant.name
  end

  test "grants create with blank reason stores nil reason" do
    post_grant(reason: "   ")

    assert_nil role_grant.reason
  end

  test "grants create with channels and blank role adds a channel grant and no role" do
    channel = Analytics::DimChannel.where(archived: false).first

    post admin_grants_path, params: { user_id: "U0AFF1", role: "",
      channels: [channel.channel_id] }
    Current.forget_roles

    assert_empty Authz.effective_roles("U0AFF1")
    assert Authz.holds?(Account.find("U0AFF1"), "channel.read"),
      "account lacks channel.read after a channel grant"
    assert Channels::Audience::Grant.live
      .exists?(user_id: "U0AFF1", channel_id: channel.channel_id)
  end

  test "grants create with role and scope and channel adds all three grants" do
    channel = Analytics::DimChannel.where(archived: false).first

    post admin_grants_path, params: { user_id: "U0AFF1", role: "gardener",
      scopes: ["channel.backfill"], channels: [channel.channel_id], reason: "the sync rota" }
    Current.forget_roles

    assert_equal "gardener", role_grant.name
    capabilities = Authz.effective_capabilities("U0AFF1")
    assert_equal "added", capabilities["channel.backfill"]
    assert_equal "baseline", capabilities["channel.read"],
      "channel.read source is not baseline for gardener"
    assert Channels::Audience::Grant.live
      .exists?(user_id: "U0AFF1", channel_id: channel.channel_id)
  end
end

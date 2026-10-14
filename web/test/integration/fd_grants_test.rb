require "test_helper"

class FdGrantsTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
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

  test "giving access records the role and who gave it" do
    post_grant

    grant = role_grant
    assert_equal "firefighter", grant.name
    assert_equal "UME", grant.granted_by
    assert_redirected_to admin_person_path("U0AFF1")
    assert Fd::AuditEntry.exists?(entity_type: "capability_grant", entity_id: grant.id,
      verb: "granted")
  end

  test "a grant needs somebody" do
    post_grant(user_id: "")
    assert_match(/Search for a member/, flash[:alert])

    post_grant(user_id: "not-an-id")
    assert_match(/is not a Slack user id/, flash[:alert])

    assert_equal 0, Authz::Grant.for_person("U0AFF1").count
  end

  test "changing a role ends the old grant and starts a new one" do
    post_grant
    post_grant(role: "gardener")

    assert_equal "gardener", role_grant.name
    assert_equal 2, Authz::Grant.for_person("U0AFF1").roles.count
    assert_equal 1, Authz::Grant.for_person("U0AFF1").roles.where.not(revoked_at: nil).count
  end

  test "taking everything back leaves the person holding nothing, and says so in the trail" do
    post_grant
    grant = role_grant

    delete admin_grant_path("U0AFF1")

    assert_nil role_grant
    assert_equal "UME", grant.reload.revoked_by
  end

  test "unpicking the fire department grant_source takes that grant back" do
    post_grant
    grant = role_grant

    post admin_grants_path, params: { user_id: "U0AFF1" }

    assert_nil role_grant
    assert Fd::AuditEntry.exists?(entity_type: "capability_grant", entity_id: grant.id,
      verb: "revoked")
  end

  test "the last manager cannot lock everybody out by taking their own back" do
    delete admin_grant_path("UME")

    assert_match(/Another administrator must revoke your own access/, flash[:alert])
    assert_predicate Account.find("UME"), :manager?
  end

  test "a lead cannot reach the grant endpoints at all" do
    delete logout_path
    firefighter = Account.create!(user_id: "ULEAD")
    Authz::Grant.grant!("ULEAD", kind: "role", name: "firefighter", by: "UME")
    Current.forget_roles
    sign_in_as(firefighter)

    post_grant

    assert_nil role_grant
    assert_redirected_to root_path
  end

  test "making somebody a manager is written to the trail, and ends their old role" do
    post_grant
    post admin_grants_path, params: { user_id: "U0AFF1", role: "community_manager" }
    Current.forget_roles

    assert_predicate Account.find("U0AFF1"), :manager?
    assert_equal "community_manager", role_grant.name
    assert_equal 1, Authz::Grant.for_person("U0AFF1").roles.where.not(revoked_at: nil).count
    assert Fd::AuditEntry.where(verb: "granted")
      .any? { |row| row.after&.dig("role") == "community_manager" }
  end

  test "the controls are only drawn for somebody who may use them" do
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

  test "the give access picker is not inside a label" do
    get admin_people_path

    assert_select %(#give-access-form .combo[data-combobox-name-value="user_id"])
    assert_select "#give-access-form label .combo", count: 0
  end

  test "a reason is kept on the grant when one is given" do
    post_grant(reason: "covering the weekend")

    assert_equal "covering the weekend", role_grant.reason
  end

  test "a grant without a reason is still allowed, since the field is optional" do
    post_grant

    grant = role_grant
    assert_nil grant.reason
    assert_equal "firefighter", grant.name
  end

  test "a blank reason is stored as nothing rather than an empty string" do
    post_grant(reason: "   ")

    assert_nil role_grant.reason
  end

  test "naming a channel on somebody with no role hands out no role" do
    channel = Analytics::DimChannel.where(archived: false).first

    post admin_grants_path, params: { user_id: "U0AFF1", role: "",
      channels: [channel.channel_id] }
    Current.forget_roles

    assert_empty Authz.effective_roles("U0AFF1")
    assert Authz.holds?(Account.find("U0AFF1"), "channel.read"),
      "channel.read is everyone's, so the channel row is enough on its own"
    assert Channels::Audience::Grant.live
      .exists?(user_id: "U0AFF1", channel_id: channel.channel_id)
  end

  test "granting a role, a scope and a channel is one act" do
    channel = Analytics::DimChannel.where(archived: false).first

    post admin_grants_path, params: { user_id: "U0AFF1", role: "gardener",
      scopes: ["channel.backfill"], channels: [channel.channel_id], reason: "the sync rota" }
    Current.forget_roles

    assert_equal "gardener", role_grant.name
    capabilities = Authz.effective_capabilities("U0AFF1")
    assert_equal "added", capabilities["channel.backfill"]
    assert_equal "baseline", capabilities["channel.read"],
      "gardener already carries channel.read, so it is not granted twice"
    assert Channels::Audience::Grant.live
      .exists?(user_id: "U0AFF1", channel_id: channel.channel_id)
  end
end

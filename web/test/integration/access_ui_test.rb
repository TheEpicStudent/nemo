require "test_helper"

class AccessUiTest < ActionDispatch::IntegrationTest
  setup do
    @manager = grant_role!("UAUIBOSS", "community_manager")
    @firefighter = Account.create!(user_id: "UAUITHEM")
    grant_role!(@firefighter.user_id, "firefighter")
    Current.forget_roles
    sign_in_as(@manager)
  end

  def capabilities
    Current.forget_roles
    Authz.effective_capabilities(@firefighter.user_id)
  end

  test "admin person page responds success" do
    get admin_person_path(@firefighter.user_id)

    assert_response :success
  end

  test "capability deny removes slack.link and delete restores it" do
    assert_includes capabilities.keys, "slack.link"

    patch admin_person_capability_path(@firefighter.user_id),
      params: { key: "slack.link", effect: "deny" }
    assert_redirected_to admin_person_path(@firefighter.user_id)
    assert_not_includes capabilities.keys, "slack.link", "deny removes the capability"

    delete admin_person_capability_path(@firefighter.user_id), params: { key: "slack.link" }
    assert_includes capabilities.keys, "slack.link", "revoke restores the role default"
  end

  test "capability allow adds channel.backfill as added" do
    assert_not_includes capabilities.keys, "channel.backfill"

    patch admin_person_capability_path(@firefighter.user_id),
      params: { key: "channel.backfill", effect: "allow" }

    assert_equal "added", capabilities["channel.backfill"]
  end

  test "capability allow for access.grant alerts cannot be delegated" do
    patch admin_person_capability_path(@firefighter.user_id),
      params: { key: "access.grant", effect: "allow" }

    assert_match(/cannot be delegated/, flash[:alert])
    assert_not_includes capabilities.keys, "access.grant"
  end

  test "channel grant for firefighter keeps role and adds no capability" do
    channel = Analytics::DimChannel.where(archived: false).first
    assert_includes capabilities.keys, "channel.all", "firefighter has channel.all"

    post admin_person_channel_grants_path(@firefighter.user_id),
      params: { channel_id: channel.channel_id }

    assert_equal ["firefighter"], Authz.effective_roles(@firefighter.user_id), "role is unchanged"
    assert_empty Authz::Grant.live.for_person(@firefighter.user_id).capabilities,
      "no capability grant is added"
    assert Channels::Audience.may_see?(@firefighter, channel)
  end

  test "channel grant for account without role allows channel visibility and assigns no role" do
    channel = Analytics::DimChannel.where(archived: false).first
    bare = Account.create!(user_id: "UAUIBARE2")

    post admin_person_channel_grants_path(bare.user_id),
      params: { channel_id: channel.channel_id }
    Current.forget_roles

    assert_empty Authz.effective_roles(bare.user_id), "no role is assigned"
    assert Channels::Audience.may_see?(bare, channel)
  end

  test "channel grant with unknown channel_id alerts is not a channel" do
    post admin_person_channel_grants_path(@firefighter.user_id), params: { channel_id: "C0NOPE" }

    assert_match(/is not a channel/, flash[:alert])
  end

  def audits(type, ref)
    Fd::AuditEntry.where(entity_type: type, entity_ref: ref).oldest_first
  end

  test "channel grant and revoke write granted and revoked audit entries" do
    channel = Analytics::DimChannel.where(archived: false).first

    post admin_person_channel_grants_path(@firefighter.user_id),
      params: { channel_id: channel.channel_id }
    delete admin_person_channel_grant_path(@firefighter.user_id, channel.channel_id)

    trail = audits("channel_audience", channel.channel_id)
    assert_equal %w[granted revoked], trail.map(&:verb)
    assert_equal [@manager.user_id, @manager.user_id], trail.map(&:actor_user_id)
    assert_equal @firefighter.user_id, trail.first.after["user_id"]
    assert_equal @manager.user_id, trail.last.after["revoked_by"]
    assert_nil Channels::Audience::Grant.live
      .find_by(user_id: @firefighter.user_id, channel_id: channel.channel_id)
  end

  test "capability revoke writes a revoked audit entry" do
    patch admin_person_capability_path(@firefighter.user_id),
      params: { key: "channel.backfill", effect: "allow" }
    delete admin_person_capability_path(@firefighter.user_id), params: { key: "channel.backfill" }

    revocation = Fd::AuditEntry.where(entity_type: "capability_grant", verb: "revoked").recent_first.first
    assert_equal "channel.backfill", revocation.after["capability"]
    assert_equal @firefighter.user_id, revocation.after["user_id"]
    assert_equal "allow", revocation.before["effect"]
    assert_equal @manager.user_id, revocation.actor_user_id
    assert_not_includes capabilities.keys, "channel.backfill"
  end

  test "capability revoke with unknown key redirects with is not a capability alert" do
    delete admin_person_capability_path(@firefighter.user_id), params: { key: "case.explode" }

    assert_redirected_to admin_person_path(@firefighter.user_id)
    assert_match(/is not a capability/, flash[:alert])
  end

  test "role channel grant allows channel visibility for role holders" do
    channel = Analytics::DimChannel.where(archived: false).first
    Authz::Grant.grant!(@firefighter.user_id, kind: "role", name: "gardener", by: @manager.user_id)
    Current.forget_roles

    post admin_role_channels_path(role: "gardener"), params: { channel_id: channel.channel_id }
    get admin_role_channels_path(role: "gardener")

    assert_response :success
    Current.forget_roles
    assert Channels::Audience.may_see?(@firefighter, channel), "role channel set grants visibility to role holders"
  end

  test "account page responds success without grants" do
    bare = Account.create!(user_id: "UAUIBARE")
    sign_in_as(bare)

    get account_path

    assert_response :success
  end
end

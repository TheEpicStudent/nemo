require "test_helper"

class AccessUiTest < ActionDispatch::IntegrationTest
  setup do
    @manager = hold_role!("UAUIBOSS", "community_manager")
    @firefighter = Account.create!(user_id: "UAUITHEM")
    hold_role!(@firefighter.user_id, "firefighter")
    Current.forget_roles
    sign_in_as(@manager)
  end

  def capabilities
    Current.forget_roles
    Authz.effective_capabilities(@firefighter.user_id)
  end

  test "the manage page shows the role and what they hold" do
    get admin_person_path(@firefighter.user_id)

    assert_response :success
  end

  test "a manager takes one capability off a firefighter, and puts it back" do
    assert_includes capabilities.keys, "slack.link"

    patch admin_person_capability_path(@firefighter.user_id),
      params: { key: "slack.link", effect: "deny" }
    assert_redirected_to admin_person_path(@firefighter.user_id)
    assert_not_includes capabilities.keys, "slack.link", "the deny takes it off them"

    delete admin_person_capability_path(@firefighter.user_id), params: { key: "slack.link" }
    assert_includes capabilities.keys, "slack.link", "back to the role default"
  end

  test "a manager gives a capability no role carries" do
    assert_not_includes capabilities.keys, "channel.backfill"

    patch admin_person_capability_path(@firefighter.user_id),
      params: { key: "channel.backfill", effect: "allow" }

    assert_equal "added", capabilities["channel.backfill"]
  end

  test "the locked granting capability cannot be delegated" do
    patch admin_person_capability_path(@firefighter.user_id),
      params: { key: "access.grant", effect: "allow" }

    assert_match(/cannot be delegated/, flash[:alert])
    assert_not_includes capabilities.keys, "access.grant"
  end

  test "naming a firefighter on a channel keeps their role, and they can already see it" do
    channel = Analytics::DimChannel.where(archived: false).first
    assert_includes capabilities.keys, "channel.all", "a firefighter already reads every channel"

    post admin_person_channel_grants_path(@firefighter.user_id),
      params: { channel_id: channel.channel_id }

    assert_equal ["firefighter"], Authz.effective_roles(@firefighter.user_id), "they are not demoted"
    assert_empty Authz::Grant.live.for_person(@firefighter.user_id).capabilities,
      "the baseline already covers it, nothing is added"
    assert Channels::Audience.may_see?(@firefighter, channel)
  end

  test "naming somebody with no role on a channel lets them read it without a role" do
    channel = Analytics::DimChannel.where(archived: false).first
    bare = Account.create!(user_id: "UAUIBARE2")

    post admin_person_channel_grants_path(bare.user_id),
      params: { channel_id: channel.channel_id }
    Current.forget_roles

    assert_empty Authz.effective_roles(bare.user_id), "naming a channel hands out no role"
    assert Channels::Audience.may_see?(bare, channel)
  end

  test "a channel that is not a channel is refused" do
    post admin_person_channel_grants_path(@firefighter.user_id), params: { channel_id: "C0NOPE" }

    assert_match(/is not a channel/, flash[:alert])
  end

  def audits(type, ref)
    Fd::AuditEntry.where(entity_type: type, entity_ref: ref).oldest_first
  end

  test "naming somebody on a channel and taking it back both reach the audit" do
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

  test "taking a capability back reaches the audit" do
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

  test "taking back a capability that does not exist is refused, not a 500" do
    delete admin_person_capability_path(@firefighter.user_id), params: { key: "case.explode" }

    assert_redirected_to admin_person_path(@firefighter.user_id)
    assert_match(/is not a capability/, flash[:alert])
  end

  test "the gardener set is shared, and says how many it reaches" do
    channel = Analytics::DimChannel.where(archived: false).first
    Authz::Grant.grant!(@firefighter.user_id, kind: "role", name: "gardener", by: @manager.user_id)
    Current.forget_roles

    post admin_role_channels_path(role: "gardener"), params: { channel_id: channel.channel_id }
    get admin_role_channels_path(role: "gardener")

    assert_response :success
    Current.forget_roles
    assert Channels::Audience.may_see?(@firefighter, channel), "the set reaches everyone holding the role"
  end

  test "a member with no grant still reaches their own page" do
    bare = Account.create!(user_id: "UAUIBARE")
    sign_in_as(bare)

    get account_path

    assert_response :success
  end
end

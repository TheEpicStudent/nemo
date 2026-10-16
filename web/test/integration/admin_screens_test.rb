require "test_helper"

class AdminScreensTest < ActionDispatch::IntegrationTest
  setup do
    @manager = grant_role!("UADBOSS", "community_manager")
  end

  test "account show renders for any signed in account" do
    sign_in_as(Account.create!(user_id: "UADNONE"))

    get account_path

    assert_response :success
  end

  test "admin index pages render for community_manager" do
    sign_in_as(@manager)

    [admin_people_path, admin_roles_path, admin_flags_path, admin_channels_path].each do |path|
      get path
      assert_response :success, "#{path} did not render"
    end
  end

  test "admin roles index renders for community_manager" do
    sign_in_as(@manager)

    get admin_roles_path

    assert_response :success
  end

  test "admin people without roles redirects to root" do
    sign_in_as(Account.create!(user_id: "UADOUT"))

    get admin_people_path

    assert_redirected_to root_path
  end

  test "admin channel update with audience public redirects and stores audience" do
    channel = Analytics::DimChannel.where(archived: false).first
    sign_in_as(@manager)

    patch admin_channel_path(channel.channel_id), params: { audience: "public" }

    assert_redirected_to admin_channels_path
    assert_equal "public", Channels::Audience.of(channel.channel_id)
  end

  test "admin channels with analytics role redirects to root" do
    sign_in_as(grant_role!("UADANA", "analytics"))

    get admin_channels_path

    assert_redirected_to root_path
  end

  test "admin channels with access.grant renders" do
    sign_in_as(grant_role!("UADCUR", "community_manager"))

    get admin_channels_path

    assert_response :success
  end

  test "admin channel update with analytics role keeps audience granted" do
    staff = grant_role!("UADANA2", "analytics")
    channel = Analytics::DimChannel.where(archived: false).first
    sign_in_as(staff)

    patch admin_channel_path(channel.channel_id), params: { audience: "public" }

    assert_equal "granted", Channels::Audience.of(channel.channel_id)
  end

  test "admin channel update with unknown audience sets alert and keeps audience" do
    sign_in_as(@manager)
    channel = Analytics::DimChannel.where(archived: false).first

    patch admin_channel_path(channel.channel_id), params: { audience: "world" }

    assert_match(/not an audience/, flash[:alert])
    assert_equal "granted", Channels::Audience.of(channel.channel_id)
  end

  test "admin channel activity toggles visibility and records audit entries" do
    channel = Analytics::DimChannel.where(archived: false).first
    sign_in_as(@manager)

    patch activity_admin_channel_path(channel.channel_id), params: { shown: "on" }

    assert_redirected_to admin_channels_path
    assert Channels::Activity.visible?(channel.channel_id)
    assert Fd::AuditEntry.where(entity_type: "message_activity", entity_ref: channel.channel_id,
      verb: "turned_on", actor_user_id: @manager.user_id).exists?

    get admin_channels_path
    assert_response :success
    assert_includes response.body, "Hide message activity"

    patch activity_admin_channel_path(channel.channel_id), params: { shown: "off" }

    refute Channels::Activity.visible?(channel.channel_id)
    assert Fd::AuditEntry.where(entity_type: "message_activity", entity_ref: channel.channel_id,
      verb: "turned_off").exists?
  ensure
    Channels::Activity::Setting.where(channel_id: channel.channel_id).delete_all
  end

  test "admin channel activity with analytics role keeps activity hidden" do
    staff = grant_role!("UADANA3", "analytics")
    channel = Analytics::DimChannel.where(archived: false).first
    sign_in_as(staff)

    patch activity_admin_channel_path(channel.channel_id), params: { shown: "on" }

    refute Channels::Activity.visible?(channel.channel_id)
  end

  test "admin channel activity with invalid value sets alert and keeps activity hidden" do
    sign_in_as(@manager)
    channel = Analytics::DimChannel.where(archived: false).first

    patch activity_admin_channel_path(channel.channel_id), params: { shown: "maybe" }

    assert_match(/not on or off/, flash[:alert])
    refute Channels::Activity.visible?(channel.channel_id)
  end
end

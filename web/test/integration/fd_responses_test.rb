require "test_helper"

class FdResponsesTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "firefighter")
    sign_in_as(@me)
    @channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    skip "the corpus has no channel" if @channel.nil?
  end

  def save_autoresponse(**over)
    post fd_configuration_autoresponse_path, params: {
      on: "1", emoji: "fd-reason, blunder", channel_id: @channel.channel_id,
      cooldown_days: "7", body: "here is why we do not say"
    }.merge(over)
  end

  def save_unsub_shield(**over)
    post fd_configuration_unsub_shield_path,
      params: { on: "1", link: "https://unsub.hack.club" }.merge(over)
  end

  def setting(key) = Fd::AppSetting.value(key)

  def seat_nemo!(channel_id, inside)
    connection = ActiveRecord::Base.connection
    connection.execute(
      "INSERT INTO fd.channel_membership (channel_id, inside) VALUES (#{connection.quote(channel_id)}, #{inside}) " \
      "ON CONFLICT (channel_id) DO UPDATE SET inside = EXCLUDED.inside"
    )
  end

  test "autoresponse channel nemo is not in shows the seat warning" do
    Fd::AppSetting.write(Fd::AppSetting::AUTORESPONSE_CHANNEL, @channel.channel_id, by: "UME")
    seat_nemo!(@channel.channel_id, false)

    get fd_configuration_path(tab: "responses")

    assert_select "p.sev-crit", "Nemo is not a member of this channel"
  end

  test "autoresponse channel nemo is in shows no seat warning" do
    Fd::AppSetting.write(Fd::AppSetting::AUTORESPONSE_CHANNEL, @channel.channel_id, by: "UME")
    seat_nemo!(@channel.channel_id, true)

    get fd_configuration_path(tab: "responses")

    assert_select "p.sev-crit", count: 0
  end

  test "the responses tab opens" do
    get fd_configuration_path(tab: "responses")

    assert_response :success
    assert_match(/Autoresponse/, response.body)
    assert_match(/Unsubscribe shield/, response.body)
  end

  test "the watched channel is named" do
    named = Analytics::DimChannel.where.not(name: nil).first
    skip "the corpus has no named channel" if named.nil?
    save_autoresponse(channel_id: named.channel_id)
    get fd_configuration_path(tab: "responses")

    assert_match(/##{named.name}/, response.body)
    assert_no_match(/unnamed channel/, response.body)
  end

  test "the tab bar shows once there is expand than one tab" do
    get fd_configuration_path

    assert_match(/Automod/, response.body)
    assert_match(/Responses/, response.body)
  end

  test "an autoresponse is saved and audited" do
    save_autoresponse

    assert Fd::AppSetting.on?(Fd::AppSetting::AUTORESPONSE_ON)
    assert_equal %w[fd-reason blunder], Fd::AppSetting.autoresponse_emoji
    assert_equal @channel.channel_id, setting(Fd::AppSetting::AUTORESPONSE_CHANNEL)
    assert_equal "here is why we do not say", setting(Fd::AppSetting::AUTORESPONSE_BODY)
    assert_equal 7, Fd::AppSetting.autoresponse_cooldown_days
    assert_operator Fd::AuditEntry.where(entity_type: "app_setting", verb: "tuned").count,
      :>=, 1
  end

  test "emoji are taken with or without colons" do
    save_autoresponse(emoji: ":fd-reason:, blunder ,:blunder:")

    assert_equal %w[fd-reason blunder], Fd::AppSetting.autoresponse_emoji
  end

  test "turning it off keeps what was typed" do
    save_autoresponse
    save_autoresponse(on: "")

    assert_not Fd::AppSetting.on?(Fd::AppSetting::AUTORESPONSE_ON)
    assert_equal "here is why we do not say", setting(Fd::AppSetting::AUTORESPONSE_BODY)
  end

  test "turning it on with no reply is refused" do
    save_autoresponse(body: "  ")

    assert_empty setting(Fd::AppSetting::AUTORESPONSE_BODY)
    assert_match(/say what to answer with/, flash[:alert])
  end

  test "turning it on with no emoji is refused" do
    save_autoresponse(emoji: " , ")

    assert_match(/at least one emoji/, flash[:alert])
  end

  test "turning it on with no channel is refused" do
    save_autoresponse(channel_id: "")

    assert_match(/pick which channel/, flash[:alert])
  end

  test "a channel we have never heard of is refused" do
    save_autoresponse(channel_id: "C0NOTHING")

    assert_match(/is not a channel/, flash[:alert])
  end

  test "a cooldown outside the range is refused" do
    save_autoresponse(cooldown_days: "0")

    assert_match(/from 1 to/, flash[:alert])
  end

  test "turning it off does not check the rest" do
    save_autoresponse(on: "", body: "", emoji: "", channel_id: "")

    assert_not Fd::AppSetting.on?(Fd::AppSetting::AUTORESPONSE_ON)
    assert_nil flash[:alert]
  end

  test "the unsubscribe shield is saved" do
    save_unsub_shield

    assert Fd::AppSetting.on?(Fd::AppSetting::UNSUB_SHIELD_ON)
    assert_equal "https://unsub.hack.club", setting(Fd::AppSetting::UNSUB_SHIELD_LINK)
  end

  test "a link that is not a valid link is refused" do
    save_unsub_shield(link: "unsub.hack.club")

    assert_empty setting(Fd::AppSetting::UNSUB_SHIELD_LINK)
    assert_match(/not a valid link/, flash[:alert])
  end

  test "the shield is turned off on its own" do
    save_unsub_shield
    save_unsub_shield(on: "")

    assert_not Fd::AppSetting.on?(Fd::AppSetting::UNSUB_SHIELD_ON)
    assert_equal "https://unsub.hack.club", setting(Fd::AppSetting::UNSUB_SHIELD_LINK)
  end

  test "somebody without the capability cannot save either" do
    drop_roles!("UME")
    hold_role!("UME", "gardener")
    save_autoresponse
    save_unsub_shield

    assert_empty setting(Fd::AppSetting::AUTORESPONSE_BODY)
    assert_empty setting(Fd::AppSetting::UNSUB_SHIELD_LINK)
  end
  test "the reply field lists the member variable" do
    get fd_configuration_path(tab: "responses")

    assert_select ".field-vars code", "{member}"
  end
end

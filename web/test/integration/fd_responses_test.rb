require "test_helper"

class FdResponsesTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "firefighter")
    sign_in_as(@me)
    @channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    skip "the corpus has no channel" if @channel.nil?
  end

  def save_autoresponse(**overrides)
    post fd_configuration_autoresponse_path, params: {
      on: "1", emoji: "fd-reason, blunder", channel_id: @channel.channel_id,
      cooldown_days: "7", body: "here is why we do not say"
    }.merge(overrides)
  end

  def save_unsub_shield(**overrides)
    post fd_configuration_unsub_shield_path,
      params: { on: "1", link: "https://unsub.hack.club" }.merge(overrides)
  end

  def setting(key) = Fd::AppSetting.value(key)

  def join_nemo!(channel_id, inside)
    connection = ActiveRecord::Base.connection
    connection.execute(
      "INSERT INTO fd.channel_membership (channel_id, inside) VALUES (#{connection.quote(channel_id)}, #{inside}) " \
      "ON CONFLICT (channel_id) DO UPDATE SET inside = EXCLUDED.inside"
    )
  end

  test "responses tab warns when nemo is not a channel member" do
    Fd::AppSetting.write(Fd::AppSetting::AUTORESPONSE_CHANNEL, @channel.channel_id, by: "UME")
    join_nemo!(@channel.channel_id, false)

    get fd_configuration_path(tab: "responses")

    assert_select "p.sev-crit", "Nemo is not a member of this channel"
  end

  test "responses tab shows no warning when nemo is a channel member" do
    Fd::AppSetting.write(Fd::AppSetting::AUTORESPONSE_CHANNEL, @channel.channel_id, by: "UME")
    join_nemo!(@channel.channel_id, true)

    get fd_configuration_path(tab: "responses")

    assert_select "p.sev-crit", count: 0
  end

  test "responses tab renders Autoresponse and Unsubscribe shield" do
    get fd_configuration_path(tab: "responses")

    assert_response :success
    assert_match(/Autoresponse/, response.body)
    assert_match(/Unsubscribe shield/, response.body)
  end

  test "responses tab shows the autoresponse channel name" do
    named = Analytics::DimChannel.where.not(name: nil).first
    skip "the corpus has no named channel" if named.nil?
    save_autoresponse(channel_id: named.channel_id)
    get fd_configuration_path(tab: "responses")

    assert_match(/##{named.name}/, response.body)
    assert_no_match(/unnamed channel/, response.body)
  end

  test "configuration index lists Automod and Responses tabs" do
    get fd_configuration_path

    assert_match(/Automod/, response.body)
    assert_match(/Responses/, response.body)
  end

  test "autoresponse save stores settings and audits tuned" do
    save_autoresponse

    assert Fd::AppSetting.on?(Fd::AppSetting::AUTORESPONSE_ON)
    assert_equal %w[fd-reason blunder], Fd::AppSetting.autoresponse_emoji
    assert_equal @channel.channel_id, setting(Fd::AppSetting::AUTORESPONSE_CHANNEL)
    assert_equal "here is why we do not say", setting(Fd::AppSetting::AUTORESPONSE_BODY)
    assert_equal 7, Fd::AppSetting.autoresponse_cooldown_days
    assert_operator Fd::AuditEntry.where(entity_type: "app_setting", verb: "tuned").count,
      :>=, 1
  end

  test "autoresponse save accepts emoji with or without colons" do
    save_autoresponse(emoji: ":fd-reason:, blunder ,:blunder:")

    assert_equal %w[fd-reason blunder], Fd::AppSetting.autoresponse_emoji
  end

  test "autoresponse save with on blank keeps the stored body" do
    save_autoresponse
    save_autoresponse(on: "")

    assert_not Fd::AppSetting.on?(Fd::AppSetting::AUTORESPONSE_ON)
    assert_equal "here is why we do not say", setting(Fd::AppSetting::AUTORESPONSE_BODY)
  end

  test "autoresponse save with blank body is refused" do
    save_autoresponse(body: "  ")

    assert_empty setting(Fd::AppSetting::AUTORESPONSE_BODY)
    assert_match(/Enter a message/, flash[:alert])
  end

  test "autoresponse save with blank emoji is refused" do
    save_autoresponse(emoji: " , ")

    assert_match(/Select an emoji/, flash[:alert])
  end

  test "autoresponse save with blank channel_id is refused" do
    save_autoresponse(channel_id: "")

    assert_match(/Select a channel/, flash[:alert])
  end

  test "autoresponse save with unknown channel_id is refused" do
    save_autoresponse(channel_id: "C0NOTHING")

    assert_match(/is not a channel/, flash[:alert])
  end

  test "autoresponse save with cooldown_days 0 is refused" do
    save_autoresponse(cooldown_days: "0")

    assert_match(/Enter 1 to 365 days/, flash[:alert])
  end

  test "autoresponse save with on blank skips validation" do
    save_autoresponse(on: "", body: "", emoji: "", channel_id: "")

    assert_not Fd::AppSetting.on?(Fd::AppSetting::AUTORESPONSE_ON)
    assert_nil flash[:alert]
  end

  test "unsub shield save stores on and link" do
    save_unsub_shield

    assert Fd::AppSetting.on?(Fd::AppSetting::UNSUB_SHIELD_ON)
    assert_equal "https://unsub.hack.club", setting(Fd::AppSetting::UNSUB_SHIELD_LINK)
  end

  test "unsub shield save with an invalid link is refused" do
    save_unsub_shield(link: "unsub.hack.club")

    assert_empty setting(Fd::AppSetting::UNSUB_SHIELD_LINK)
    assert_match(/not a valid link/, flash[:alert])
  end

  test "unsub shield save with on blank keeps the stored link" do
    save_unsub_shield
    save_unsub_shield(on: "")

    assert_not Fd::AppSetting.on?(Fd::AppSetting::UNSUB_SHIELD_ON)
    assert_equal "https://unsub.hack.club", setting(Fd::AppSetting::UNSUB_SHIELD_LINK)
  end

  test "autoresponse and unsub shield save without the capability store nothing" do
    revoke_roles!("UME")
    grant_role!("UME", "gardener")
    save_autoresponse
    save_unsub_shield

    assert_empty setting(Fd::AppSetting::AUTORESPONSE_BODY)
    assert_empty setting(Fd::AppSetting::UNSUB_SHIELD_LINK)
  end
  test "responses tab reply field lists the member variable" do
    get fd_configuration_path(tab: "responses")

    assert_select ".field-vars code", "{member}"
  end
end

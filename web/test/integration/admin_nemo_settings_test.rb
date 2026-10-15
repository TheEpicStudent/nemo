require "test_helper"

class AdminNemoSettingsTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def setting(key) = Fd::AppSetting.value(key)

  def save_sweep_settings(**over)
    post admin_settings_sweep_path, params: { soon_hours: "12", tells: "1" }.merge(over)
  end

  CHANNEL_KEYS = [Fd::AppSetting::FIREHOUSE, Fd::AppSetting::REPORTS, Fd::AppSetting::LOGS].freeze

  def known_channel_id
    channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    skip "the corpus has no channel" if channel.nil?
    channel.channel_id
  end

  test "settings page without channel settings shows a warning for each" do
    Fd::AppSetting.where(key: CHANNEL_KEYS).delete_all

    get admin_settings_path

    assert_equal ["No firehouse picked", "No channel picked", "No channel picked"],
      css_select("p.empty-title.sev-crit").map { |node| node.text.strip }
  end

  test "settings page with channel settings shows no warning" do
    CHANNEL_KEYS.each { |key| Fd::AppSetting.write(key, "C0FIRE", by: "UME") }

    get admin_settings_path

    assert_select "p.sev-crit", count: 0
  end

  test "reports_channel saves the picked channel and audits it" do
    channel_id = known_channel_id

    post admin_settings_reports_channel_path, params: { channel_id: channel_id }

    assert_redirected_to admin_settings_path
    assert_equal channel_id, setting(Fd::AppSetting::REPORTS)
    assert_match(/\AShroud reports now post to #/, flash[:notice])
    assert Fd::AuditEntry.exists?(verb: "tuned")
  end

  test "log_channel saves the picked channel apart from the firehouse" do
    channel_id = known_channel_id
    Fd::AppSetting.set_firehouse_channel("C0FIRE", by: "UME")

    post admin_settings_log_channel_path, params: { channel_id: channel_id }

    assert_equal [channel_id, "C0FIRE"], [setting(Fd::AppSetting::LOGS), setting(Fd::AppSetting::FIREHOUSE)]
    assert_match(/\ANemo logs now post to #/, flash[:notice])
  end

  test "log_channel refuses a channel that does not exist" do
    post admin_settings_log_channel_path, params: { channel_id: "C0NOSUCH" }

    assert_equal "C0NOSUCH is not a channel", flash[:alert]
    assert_equal "", setting(Fd::AppSetting::LOGS)
  end

  test "firehouse notice names the firehouse" do
    channel_id = known_channel_id

    post admin_settings_firehouse_path, params: { channel_id: channel_id }

    assert_equal channel_id, setting(Fd::AppSetting::FIREHOUSE)
    assert_match(/\AThe firehouse is now #/, flash[:notice])
  end

  test "the settings page carries both" do
    get admin_settings_path

    assert_response :success
    assert_match(/Channels Nemo joins/, response.body)
    assert_match(/Guard expiry/, response.body)
  end

  test "the join mode is set here" do
    post admin_settings_join_mode_path, params: { mode: "on" }

    assert_equal "on", Fd::AppSetting.join_mode
    assert_equal 1, Fd::AuditEntry.where(entity_type: "app_setting", verb: "tuned").count
  end

  test "a join mode that is not one is refused" do
    post admin_settings_join_mode_path, params: { mode: "sideways" }

    assert_equal "guarded", Fd::AppSetting.join_mode
    assert_match(/not a valid join mode/, flash[:alert])
  end

  test "setting the mode it already has changes nothing" do
    post admin_settings_join_mode_path, params: { mode: "guarded" }

    assert_equal 0, Fd::AuditEntry.where(entity_type: "app_setting", verb: "tuned").count
  end

  test "the sweep horizon is saved" do
    save_sweep_settings

    assert_equal 12, Fd::AppSetting.sweep_soon_hours
    assert Fd::AppSetting.sweep_tells_member?
  end

  test "the horizon falls back when it was never set" do
    assert_equal 36, Fd::AppSetting.sweep_soon_hours
    assert Fd::AppSetting.sweep_tells_member?
  end

  test "an horizon outside the range is refused" do
    save_sweep_settings(soon_hours: "0")

    assert_empty setting(Fd::AppSetting::SWEEP_SOON_HOURS)
    assert_match(/from 1 to/, flash[:alert])
  end

  test "telling the member is turned off on its own" do
    save_sweep_settings(tells: "")

    assert_equal 12, Fd::AppSetting.sweep_soon_hours
    assert_not Fd::AppSetting.sweep_tells_member?
  end

  test "the channels page shows the mode but cannot change it" do
    get fd_channels_path

    assert_response :success
    assert_no_match(/join_mode/, response.body)
  end

  test "somebody who is not a community manager is turned away" do
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    post admin_settings_join_mode_path, params: { mode: "on" }

    assert_equal "guarded", Fd::AppSetting.join_mode
  end
end

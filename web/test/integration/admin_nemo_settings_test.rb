require "test_helper"

class AdminNemoSettingsTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
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

    assert_equal ["No channel selected"] * 3,
      css_select(".setname p.sev-crit").map { |node| node.text.strip }
  end

  test "settings page with channel settings shows no warning" do
    CHANNEL_KEYS.each { |key| Fd::AppSetting.write(key, "C0FIRE", by: "UME") }

    get admin_settings_path

    assert_select "p.sev-crit", count: 0
  end

  def join_nemo!(channel_id, inside)
    connection = ActiveRecord::Base.connection
    connection.execute(
      "INSERT INTO fd.channel_membership (channel_id, inside) VALUES (#{connection.quote(channel_id)}, #{inside}) " \
      "ON CONFLICT (channel_id) DO UPDATE SET inside = EXCLUDED.inside"
    )
  end

  def refuse_join!(channel_id, why)
    connection = ActiveRecord::Base.connection
    connection.execute(
      "INSERT INTO fd.channel_joins (channel_id, verb, why) " \
      "VALUES (#{connection.quote(channel_id)}, 'refused', #{connection.quote(why)})"
    )
  end

  test "settings page with firehouse channel not joined shows not a member warning" do
    Fd::AppSetting.set_firehouse_channel("C0FIRE", by: "UME")
    join_nemo!("C0FIRE", false)

    get admin_settings_path

    assert_select ".setname p.sev-crit", "Nemo is not a member of this channel"
  end

  test "settings page with react channel needing an invite shows invite note" do
    Fd::AppSetting.set_case_react_channels(["G0PRIVATE"], by: "UME")
    join_nemo!("G0PRIVATE", false)
    refuse_join!("G0PRIVATE", FdChannelsHelper::NEEDS_INVITE)

    get admin_settings_path

    assert_select ".setname p.sev-crit", FdChannelsHelper::INVITE_NOTE
  end

  test "settings page with all configured channels joined shows no warning" do
    CHANNEL_KEYS.each { |key| Fd::AppSetting.write(key, "C0FIRE", by: "UME") }
    Fd::AppSetting.set_case_react_channels(["C0REACT"], by: "UME")
    join_nemo!("C0FIRE", true)
    join_nemo!("C0REACT", true)

    get admin_settings_path

    assert_select ".setname p.sev-crit", count: 0
  end

  test "reports_channel saves the channel and audits it" do
    channel_id = known_channel_id

    post admin_settings_reports_channel_path, params: { channel_id: channel_id }

    assert_redirected_to admin_settings_path
    assert_equal channel_id, setting(Fd::AppSetting::REPORTS)
    assert_match(/\AShroud reports channel set to #/, flash[:notice])
    assert Fd::AuditEntry.exists?(verb: "tuned")
  end

  test "log_channel saves the channel and keeps the firehouse channel" do
    channel_id = known_channel_id
    Fd::AppSetting.set_firehouse_channel("C0FIRE", by: "UME")

    post admin_settings_log_channel_path, params: { channel_id: channel_id }

    assert_equal [channel_id, "C0FIRE"], [setting(Fd::AppSetting::LOGS), setting(Fd::AppSetting::FIREHOUSE)]
    assert_match(/\AInternal logs channel set to #/, flash[:notice])
  end

  test "log_channel with unknown channel sets alert and saves nothing" do
    post admin_settings_log_channel_path, params: { channel_id: "C0NOSUCH" }

    assert_equal "C0NOSUCH is not a known channel", flash[:alert]
    assert_equal "", setting(Fd::AppSetting::LOGS)
  end

  test "firehouse saves the channel and sets the notice" do
    channel_id = known_channel_id

    post admin_settings_firehouse_path, params: { channel_id: channel_id }

    assert_equal channel_id, setting(Fd::AppSetting::FIREHOUSE)
    assert_match(/\AFirehouse channel set to #/, flash[:notice])
  end

  test "settings page renders channels and guard expiry sections" do
    get admin_settings_path

    assert_response :success
    assert_match(/Channels Nemo joins/, response.body)
    assert_match(/Guard expiry/, response.body)
  end

  test "join_mode saves the mode and audits it" do
    post admin_settings_join_mode_path, params: { mode: "on" }

    assert_equal "on", Fd::AppSetting.join_mode
    assert_equal 1, Fd::AuditEntry.where(entity_type: "app_setting", verb: "tuned").count
  end

  test "join_mode off sets the configured only notice and card" do
    post admin_settings_join_mode_path, params: { mode: "off" }

    assert_equal "Join mode set to Configured only", flash[:notice]
    follow_redirect!
    assert_select "p.card-sub", "Configured channels only"
  end

  test "join_mode with an invalid value is refused and keeps guarded" do
    post admin_settings_join_mode_path, params: { mode: "sideways" }

    assert_equal "guarded", Fd::AppSetting.join_mode
    assert_match(/not a valid join mode/, flash[:alert])
  end

  test "join_mode with the current value writes no audit entry" do
    post admin_settings_join_mode_path, params: { mode: "guarded" }

    assert_equal 0, Fd::AuditEntry.where(entity_type: "app_setting", verb: "tuned").count
  end

  test "sweep settings save soon_hours and member notice" do
    save_sweep_settings

    assert_equal 12, Fd::AppSetting.sweep_soon_hours
    assert Fd::AppSetting.sweep_tells_member?
  end

  test "sweep settings default to 36 hours with member notice on" do
    assert_equal 36, Fd::AppSetting.sweep_soon_hours
    assert Fd::AppSetting.sweep_tells_member?
  end

  test "sweep settings with soon_hours outside the range are refused" do
    save_sweep_settings(soon_hours: "0")

    assert_empty setting(Fd::AppSetting::SWEEP_SOON_HOURS)
    assert_match(/from 1 to/, flash[:alert])
  end

  test "sweep settings with blank tells turn member notice off and keep soon_hours" do
    save_sweep_settings(tells: "")

    assert_equal 12, Fd::AppSetting.sweep_soon_hours
    assert_not Fd::AppSetting.sweep_tells_member?
  end

  test "channels page body does not include join_mode" do
    get fd_channels_path

    assert_response :success
    assert_no_match(/join_mode/, response.body)
  end

  test "join_mode as firefighter keeps guarded" do
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    post admin_settings_join_mode_path, params: { mode: "on" }

    assert_equal "guarded", Fd::AppSetting.join_mode
  end

  ACCOUNT_KEYS = [Fd::AppSetting::DEACTIVATE, Fd::AppSetting::SESSION_RESET,
                  Fd::AppSetting::SESSION_RESET_STRIKES, Fd::AppSetting::SESSION_RESET_MAX].freeze

  def save_account_settings(**over)
    post admin_settings_accounts_path,
      params: { deactivate: "on", session_reset: "off", strikes: "3", resets: "0" }.merge(over)
  end

  def tuned_count = Fd::AuditEntry.where(entity_type: "app_setting", verb: "tuned").count

  test "account settings save every value" do
    Fd::AppSetting.where(key: ACCOUNT_KEYS).delete_all

    save_account_settings

    assert_redirected_to admin_settings_path
    assert_equal "Account action settings saved", flash[:notice]
    assert_equal ["on", "off", 3, 0],
      [Fd::AppSetting.deactivate_mode, Fd::AppSetting.session_reset_mode,
       Fd::AppSetting.session_reset_strikes, Fd::AppSetting.session_reset_max]
    assert_equal 4, tuned_count
  end

  test "account settings unset render log only and default strikes and resets" do
    Fd::AppSetting.where(key: ACCOUNT_KEYS).delete_all

    get admin_settings_path

    assert_select "select[name=deactivate] option[selected]", "Log only"
    assert_select "select[name=session_reset] option[selected]", "Log only"
    assert_select "input[name=strikes][value='2']"
    assert_select "input[name=resets][value='5']"
  end

  test "account settings unchanged value keeps changed_by and writes no audit entry" do
    Fd::AppSetting.write(Fd::AppSetting::DEACTIVATE, "on", by: "UOTHER")
    Fd::AppSetting.where(key: ACCOUNT_KEYS - [Fd::AppSetting::DEACTIVATE]).delete_all

    save_account_settings

    assert_equal "UOTHER", Fd::AppSetting.find(Fd::AppSetting::DEACTIVATE).changed_by
    assert_equal 3, tuned_count
  end

  test "account settings with an unknown mode change nothing" do
    Fd::AppSetting.where(key: ACCOUNT_KEYS).delete_all

    save_account_settings(session_reset: "sometimes")

    assert_equal "That is not a valid mode", flash[:alert]
    assert_equal 0, Fd::AppSetting.where(key: ACCOUNT_KEYS).count
  end

  test "account settings with strikes outside the range change nothing" do
    Fd::AppSetting.where(key: ACCOUNT_KEYS).delete_all

    save_account_settings(strikes: "0")

    assert_match(/from 1 to/, flash[:alert])
    assert_equal 0, Fd::AppSetting.where(key: ACCOUNT_KEYS).count
  end

  test "account settings with non numeric resets change nothing" do
    Fd::AppSetting.where(key: ACCOUNT_KEYS).delete_all

    save_account_settings(resets: "lots")

    assert_match(/from 0 to/, flash[:alert])
    assert_equal 0, Fd::AppSetting.where(key: ACCOUNT_KEYS).count
  end

  test "trusted senders add stores the member and audits it" do
    Fd::AppSetting.where(key: Fd::AppSetting::TRUSTED_SENDERS).delete_all

    post admin_settings_trusted_senders_path, params: { user_id: "u0akqnskbk4" }

    assert_redirected_to admin_settings_path
    assert_equal ["U0AKQNSKBK4"], Fd::AppSetting.trusted_senders
    assert Fd::AuditEntry.exists?(entity_type: "app_setting", verb: "tuned")
  end

  test "trusted senders add refuses a value that is not a member id" do
    post admin_settings_trusted_senders_path, params: { user_id: "prometheus" }

    assert_equal "PROMETHEUS is not a member id", flash[:alert]
  end

  test "trusted senders remove drops only that member" do
    Fd::AppSetting.set_trusted_senders(%w[U0AKQNSKBK4 U0OTHER123], by: "UME")

    delete admin_settings_trusted_sender_path("U0AKQNSKBK4")

    assert_equal ["U0OTHER123"], Fd::AppSetting.trusted_senders
  end

  test "settings page lists trusted senders with a remove button" do
    Fd::AppSetting.set_trusted_senders(%w[U0AKQNSKBK4], by: "UME")

    get admin_settings_path

    assert_select "h2.card-title", text: "Trusted senders"
    assert_select "form[action='#{admin_settings_trusted_sender_path("U0AKQNSKBK4")}'] button", text: "Remove"
  end

  test "settings page without trusted senders shows a bare title" do
    Fd::AppSetting.where(key: Fd::AppSetting::TRUSTED_SENDERS).delete_all

    get admin_settings_path

    assert_select ".empty-title", text: "No trusted senders"
  end
end

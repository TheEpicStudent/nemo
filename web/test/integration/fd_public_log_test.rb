require "test_helper"

class FdPublicLogTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "firefighter")
    sign_in_as(@me)
    @channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    skip "the corpus has no channel" if @channel.nil?
  end

  def setting(key) = Fd::AppSetting.value(key)

  def save_event(event, **overrides)
    patch fd_configuration_public_log_event_path(event),
      params: { on: "1", template: "{admin} locked {thread}" }.merge(overrides)
  end

  test "public log tab renders a card per event" do
    get fd_configuration_path(tab: "public_log")

    assert_response :success
    Fd::PublicLog.events.each { |event| assert_select "h2.card-title", Fd::PublicLog.label(event) }
    assert_select "p.sev-crit", "No channel picked"
  end

  test "public log tab shows the current channel" do
    Fd::AppSetting.write(Fd::PublicLog::CHANNEL_KEY, @channel.channel_id, by: "UME")

    get fd_configuration_path(tab: "public_log")

    assert_select "p.sev-crit", text: "No channel picked", count: 0
  end

  test "channel save stores the channel and audits tuned" do
    post fd_configuration_public_log_channel_path, params: { channel_id: @channel.channel_id }

    assert_equal @channel.channel_id, setting(Fd::PublicLog::CHANNEL_KEY)
    assert_operator Fd::AuditEntry.where(entity_type: "app_setting", verb: "tuned").count, :>=, 1
  end

  test "channel save with a blank or unknown channel is refused" do
    post fd_configuration_public_log_channel_path, params: { channel_id: "" }
    assert_match(/Select a channel/, flash[:alert])

    post fd_configuration_public_log_channel_path, params: { channel_id: "CNOPE" }
    assert_match(/is not a channel/, flash[:alert])
    assert_empty setting(Fd::PublicLog::CHANNEL_KEY)
  end

  test "event save stores the switch and template" do
    save_event("lock")

    assert Fd::PublicLog.enabled?("lock")
    assert_equal "{admin} locked {thread}", Fd::PublicLog.template("lock")
    assert Fd::PublicLog.customised?("lock")
  end

  test "event save keeps line breaks and ignores carriage returns" do
    save_event("lock", template: "{admin} locked\r\n{thread}")

    assert_equal "{admin} locked\n{thread}", Fd::PublicLog.template("lock")
  end

  test "event save of the default template with carriage returns stores no template" do
    save_event("lock", template: Fd::PublicLog.default_template("lock").gsub("\n", "\r\n"))

    assert_not Fd::PublicLog.customised?("lock")
  end

  test "event save with on blank turns the event off" do
    save_event("lock", on: "")

    assert_not Fd::PublicLog.enabled?("lock")
  end

  test "event save of an unchanged default template stores no template" do
    save_event("lock", template: Fd::PublicLog.default_template("lock"))

    assert_not Fd::PublicLog.customised?("lock")
  end

  test "event save with an unknown variable is refused" do
    save_event("lock", template: "{admin} locked {nonsense}")

    assert_match(/Unknown variable \{nonsense\}/, flash[:alert])
    assert_not Fd::PublicLog.customised?("lock")
  end

  test "event save with a variable the event does not carry is refused" do
    save_event("lock", template: "{count} locked")

    assert_match(/Unknown variable \{count\}/, flash[:alert])
  end

  test "event save with a blank template is refused" do
    save_event("lock", template: " ")

    assert_match(/Enter a template/, flash[:alert])
  end

  test "event save for an unknown event is not found" do
    save_event("nonsense")

    assert_response :not_found
  end

  test "reset removes the custom template and audits reset" do
    save_event("lock")
    delete fd_configuration_public_log_event_path("lock")

    assert_not Fd::PublicLog.customised?("lock")
    assert_equal Fd::PublicLog.default_template("lock"), Fd::PublicLog.template("lock")
    assert_operator Fd::AuditEntry.where(entity_type: "app_setting", verb: "reset").count, :>=, 1
  end

  test "defaults enable lock and destroy only" do
    assert_equal %w[lock destroy], Fd::PublicLog.events.select { |event| Fd::PublicLog.enabled?(event) }
  end

  test "event save without app.configure is refused" do
    sign_in_as(grant_role!("UPLAIN", "analytics"))

    save_event("lock")

    assert_not Fd::PublicLog.customised?("lock")
  end
end

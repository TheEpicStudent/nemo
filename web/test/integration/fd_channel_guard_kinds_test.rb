require "test_helper"

class FdChannelGuardKindsTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    @channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    skip "the corpus has no channel" if @channel.nil?
    @id = @channel.channel_id
  end

  def guard!(kind, **settings)
    Fd::ChannelGuard.create!(kind: kind, channel_id: @id, opened_by: "UME",
      settings: settings.stringify_keys)
  end

  def live(kind) = Fd::ChannelGuard.live_for(@id, kind: kind)

  def with_reason(kind, params)
    kind == "slowmode" ? { reason: "Heated argument" }.merge(params) : params
  end

  def post_guard(kind, **params)
    post fd_channel_guard_path(@id, kind), params: with_reason(kind, params)
  end

  def patch_guard(kind, **params)
    patch fd_channel_guard_path(@id, kind), params: with_reason(kind, params)
  end

  test "every tab opens" do
    Fd::ChannelsController::TABS.each do |tab|
      get fd_channel_path(@id, tab: tab)
      assert_response :success, "#{tab} did not open"
    end
  end

  test "an unknown tab falls back to the first" do
    get fd_channel_path(@id, tab: "sideways")

    assert_response :success
    assert_match(/Guards/, response.body)
  end

  test "read-only is turned on and off on its own" do
    post_guard("readonly")

    assert live("readonly")
    assert_nil live("bot_allowlist")

    delete fd_channel_guard_path(@id, "readonly")
    assert_nil live("readonly")
  end

  test "read-only keeps whether it also catches threads" do
    post_guard("readonly", threads: "1")

    assert live("readonly").threads?
  end

  test "read-only without threads leaves them out" do
    post_guard("readonly")

    assert_not live("readonly").threads?
  end

  test "read-only is retuned in place and audited" do
    post_guard("readonly")
    patch_guard("readonly", threads: "1")

    assert live("readonly").threads?
    assert_equal 1, Fd::AuditEntry.where(entity_type: "channel_guard", verb: "tuned").count
  end

  test "all four kinds stand at once on one channel" do
    Fd::ChannelGuard::KINDS.each do |kind|
      guard!(kind, seconds: 30, min_age_days: 7)
    end

    assert_equal 4, Fd::ChannelGuard.live.where(channel_id: @id).count
  end

  test "a kind that is not a kind is refused" do
    post_guard("sideways")

    assert_equal 0, Fd::ChannelGuard.live.where(channel_id: @id).count
    assert_match(/not a valid guard kind/, flash[:alert])
  end

  test "slow mode keeps the seconds it was given" do
    post_guard("slowmode", seconds: "45", threads: "1")
    guard = live("slowmode")

    assert_equal 45, guard.seconds
    assert guard.threads?
  end

  test "slow mode without threads leaves them out" do
    post_guard("slowmode", seconds: "45")

    assert_not live("slowmode").threads?
  end

  test "the switch turns slow mode on with an interval to start from" do
    post_guard("slowmode")

    assert_equal Fd::ChannelGuard::SECONDS_TO_START, live("slowmode").seconds
    assert_nil flash[:alert]
  end

  test "the switch turns the age gate on with days to start from" do
    post_guard("account_age")

    assert_equal Fd::ChannelGuard::DAYS_TO_START, live("account_age").min_age_days
    assert_nil flash[:alert]
  end

  test "slow mode refuses a interval outside the range" do
    post_guard("slowmode", seconds: "0")
    assert_nil live("slowmode")

    post_guard("slowmode", seconds: "99999")
    assert_nil live("slowmode")
    assert_equal "Enter 1 to 3600 seconds", flash[:alert]
  end

  test "slow mode without a reason is refused" do
    post_guard("slowmode", reason: " ")

    assert_nil live("slowmode")
    assert_equal "Enter a reason", flash[:alert]
  end

  test "slow mode with a duration ends after it and asks nemo for the notice" do
    freeze_time do
      post_guard("slowmode", duration: "2h")
      guard = live("slowmode")

      assert_equal 2.hours.from_now, guard.expires_at
      assert_equal "Heated argument", guard.reason
      assert guard.notice_wanted
      assert_equal "Slow mode enabled · ends #{Fd::ShortDate.ending(2.hours.from_now)}", flash[:notice]
    end
  end

  test "slow mode without a duration runs until turned off" do
    post_guard("slowmode")

    assert_nil live("slowmode").expires_at
    assert_equal "Slow mode enabled · no end date", flash[:notice]
  end

  test "slow mode with a custom end ends at that time in utc" do
    post_guard("slowmode", duration: "custom", expires_on: 2.days.from_now.to_date.to_s, expires_time: "14:30")

    assert_equal 2.days.from_now.utc.change(hour: 14, min: 30), live("slowmode").expires_at
  end

  test "slow mode with a custom end in the past is refused" do
    post_guard("slowmode", duration: "custom", expires_on: 1.day.ago.to_date.to_s)

    assert_nil live("slowmode")
    assert_equal "End must be in the future", flash[:alert]
  end

  test "slow mode with custom picked and no date is refused" do
    post_guard("slowmode", duration: "custom")

    assert_nil live("slowmode")
    assert_equal "Enter the end date", flash[:alert]
  end

  test "slow mode extend adds to the current end and is audited" do
    post_guard("slowmode", duration: "1h")
    first_end = live("slowmode").expires_at
    patch_guard("slowmode", extend_by: "30m")

    assert_equal first_end + 30.minutes, live("slowmode").expires_at
    extended = Fd::AuditEntry.where(entity_type: "channel_guard", verb: "extended").sole
    assert_equal first_end.iso8601, extended.before["expires_at"]
  end

  test "slow mode with no end is extended from now" do
    post_guard("slowmode")
    freeze_time do
      patch_guard("slowmode", extend_by: "1h")

      assert_equal 1.hour.from_now, live("slowmode").expires_at
    end
  end

  test "slow mode extend without a choice is refused" do
    post_guard("slowmode", duration: "1h")
    patch_guard("slowmode")

    assert_equal "Select how long to extend", flash[:alert]
  end

  test "slow mode enabled again starts with no exemptions" do
    post_guard("slowmode")
    post fd_channel_allows_path(@id, "slowmode"), params: { subject_ids: ["USLOW"] }
    delete fd_channel_guard_path(@id, "slowmode")
    assert_equal "Slow mode disabled", flash[:notice]
    post_guard("slowmode")

    assert_empty live("slowmode").allows
  end

  test "slow mode tab shows time left with extend and disable" do
    post_guard("slowmode", duration: "2h", threads: "1")

    get fd_channel_path(@id, tab: "slowmode")

    assert_select ".setline .setval", /\Ain (1h 59m|2h 0m) · /
    assert_select ".setline .setval", "Included"
    assert_select "[data-modal-id-value=slowmode-extend] select[name=extend_by]"
    assert_select "form[action=?] button", fd_channel_guard_path(@id, "slowmode"), text: "Disable"
  end

  test "slow mode tab when off offers the enable dialog with no end by default" do
    get fd_channel_path(@id, tab: "slowmode")

    assert_select ".empty-title", "Off"
    assert_select "[data-modal-id-value=slowmode-enable] select[name=duration] option[value=\"\"]", "No end"
  end

  test "read-only asks nemo for no notice" do
    post_guard("readonly")

    assert_not live("readonly").notice_wanted
  end

  test "an account age gate keeps its days" do
    post_guard("account_age", min_age_days: "7")

    assert_equal 7, live("account_age").min_age_days
  end

  test "an account age outside the range is refused" do
    post_guard("account_age", min_age_days: "0")

    assert_nil live("account_age")
    assert_match(/from 1 to/, flash[:alert])
  end

  test "tuning a kind that is not on is refused" do
    patch_guard("slowmode", seconds: "30")

    assert_match(/not guarded that way/, flash[:alert])
  end

  test "a member is let past read-only" do
    guard!("readonly")
    post fd_channel_allows_path(@id, "readonly"), params: { subject_ids: ["USOMEBODY"] }

    assert_equal ["USOMEBODY"], live("readonly").allows.pluck(:subject_id)
  end

  test "an allow lands on the kind it was added under" do
    guard!("readonly")
    guard!("slowmode", seconds: 30)
    post fd_channel_allows_path(@id, "readonly"), params: { subject_ids: ["USOMEBODY"] }

    assert_equal 1, live("readonly").allows.count
    assert_equal 0, live("slowmode").allows.count
  end

  test "account age exemption is saved on the gate" do
    guard!("account_age", min_age_days: 7)
    post fd_channel_allows_path(@id, "account_age"), params: { subject_ids: ["USOMEBODY"] }

    assert_redirected_to fd_channel_path(@id, tab: "account_age")
    assert_equal ["USOMEBODY"], live("account_age").allows.pluck(:subject_id)
  end

  test "account age tab lists exemptions with the exempt button" do
    guard!("account_age", min_age_days: 7).allows.create!(subject_id: "USOMEBODY", added_by: "UME")

    get fd_channel_path(@id, tab: "account_age")

    assert_select ".card-tools button", text: "Exempt member"
    assert_match "USOMEBODY", response.body
    assert_select "#allow-bot"
  end

  test "account age tab without exemptions shows no empty state" do
    guard!("account_age", min_age_days: 7)

    get fd_channel_path(@id, tab: "account_age")

    assert_no_match "No exemptions", response.body
  end

  test "account age turned back on restores its exemptions" do
    post_guard("account_age")
    post fd_channel_allows_path(@id, "account_age"), params: { subject_ids: ["USOMEBODY"] }
    delete fd_channel_guard_path(@id, "account_age")
    post_guard("account_age")

    assert_equal ["USOMEBODY"], live("account_age").allows.pluck(:subject_id)
  end

  test "an allow on a kind nobody guards is refused" do
    post fd_channel_allows_path(@id, "readonly"), params: { subject_ids: ["USOMEBODY"] }

    assert_match(/not guarded/, flash[:alert])
  end

  test "turning a guard back on restores its allow list" do
    post_guard("readonly")
    post fd_channel_allows_path(@id, "readonly"), params: { subject_ids: ["USOMEBODY", "UOTHER"] }
    delete fd_channel_guard_path(@id, "readonly")
    post_guard("readonly")

    guard = live("readonly")
    assert_equal ["UOTHER", "USOMEBODY"], guard.allows.pluck(:subject_id).sort
    assert_equal "Read-only turned on, 2 kept on the list", flash[:notice]
    restored = Fd::AuditEntry.where(entity_type: "channel_allow", entity_id: guard.id, verb: "added")
    assert_equal 2, restored.count
  end

  test "restoring keeps who added each allow" do
    post_guard("bot_allowlist")
    post fd_channel_allows_path(@id, "bot_allowlist"), params: { subject_ids: ["B0BOT"] }
    delete fd_channel_guard_path(@id, "bot_allowlist")
    post_guard("bot_allowlist")

    assert_equal ["UME"], live("bot_allowlist").allows.pluck(:added_by)
  end

  test "a guard turned on for the first time starts with no allows" do
    post_guard("readonly")

    assert_empty live("readonly").allows
    assert_equal "Read-only turned on", flash[:notice]
  end

  test "restoring takes allows only from the same kind" do
    post_guard("slowmode")
    post fd_channel_allows_path(@id, "slowmode"), params: { subject_ids: ["USLOW"] }
    delete fd_channel_guard_path(@id, "slowmode")
    post_guard("readonly")

    assert_empty live("readonly").allows
  end

  test "the overview names every kind" do
    get fd_channel_path(@id, tab: "overview")

    assert_match(/Bot allow list/, response.body)
    assert_match(/Read-only/, response.body)
    assert_match(/Slow mode/, response.body)
    assert_match(/New accounts/, response.body)
  end

  test "activity sits under the kind it belongs to" do
    bots = guard!("bot_allowlist")
    ro = guard!("readonly")
    Fd::ChannelGuardEvent.create!(guard_id: bots.id, channel_id: @id,
      subject_id: "B0CACHET", verb: "kicked")
    Fd::ChannelGuardEvent.create!(guard_id: ro.id, channel_id: @id,
      subject_id: "USOMEBODY", verb: "deleted")

    get fd_channel_path(@id, tab: "bots")
    assert_match(/B0CACHET/, response.body)
    assert_no_match(/USOMEBODY/, response.body)

    get fd_channel_path(@id, tab: "readonly")
    assert_match(/USOMEBODY/, response.body)
    assert_no_match(/B0CACHET/, response.body)
  end

  test "activity outlives the guard that recorded it" do
    guard = guard!("readonly")
    Fd::ChannelGuardEvent.create!(guard_id: guard.id, channel_id: @id,
      subject_id: "USOMEBODY", verb: "deleted")
    delete fd_channel_guard_path(@id, "readonly")
    get fd_channel_path(@id, tab: "readonly")

    assert_match(/USOMEBODY/, response.body)
  end

  test "a tab with no activity shows no activity card" do
    guard!("readonly")
    get fd_channel_path(@id, tab: "readonly")

    assert_no_match(/Activity/, response.body)
  end

  def thread_slowmode!(thread_ts: "1700000000.000100", seconds: 30, **attrs)
    Fd::ChannelGuard.create!(kind: "slowmode", channel_id: @id, thread_ts: thread_ts, opened_by: "UME",
      settings: { "seconds" => seconds }, reason: "Heated argument", **attrs)
  end

  test "thread slow mode is listed on the slow mode tab" do
    ends = 2.days.from_now.utc.change(hour: 14, min: 30)
    thread_slowmode!(expires_at: ends)

    get fd_channel_path(@id, tab: "slowmode")

    assert_select ".card-title", "Threads"
    assert_match "30s cooldown · ends in ", response.body
    assert_match Fd::ShortDate.ending(ends), response.body
    assert_match "Reason: Heated argument", response.body
    assert_select "form[action=?]", fd_channel_thread_slowmode_path(@id, Fd::ChannelGuard.thread_scoped.sole)
  end

  test "thread slow mode is not the channel slow mode" do
    thread_slowmode!

    assert_nil live("slowmode")
    post_guard("slowmode")

    assert live("slowmode")
    assert_equal "", live("slowmode").thread_ts
    assert_equal 2, Fd::ChannelGuard.live.where(channel_id: @id, kind: "slowmode").count
  end

  test "thread slow mode is disabled from the slow mode tab" do
    guard = thread_slowmode!

    delete fd_channel_thread_slowmode_path(@id, guard)

    assert_redirected_to fd_channel_path(@id, tab: "slowmode")
    assert_equal "Thread slow mode disabled", flash[:notice]
    assert_equal "lifted", guard.reload.state
    assert_equal "UME", guard.lifted_by
    assert Fd::AuditEntry.exists?(entity_type: "channel_guard", entity_id: guard.id, verb: "lifted")
  end

  test "thread slow mode is left out of the guarded channel list" do
    thread_slowmode!

    assert_equal 0, Fd::LiveGuards.new.total
  end

  test "somebody without channel.guard cannot turn a kind on" do
    drop_roles!("UME")
    hold_role!("UME", "gardener")
    post_guard("readonly")

    assert_equal 0, Fd::ChannelGuard.live.where(channel_id: @id).count
  end
end

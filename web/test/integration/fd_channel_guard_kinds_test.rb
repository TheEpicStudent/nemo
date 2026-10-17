require "test_helper"

class FdChannelGuardKindsTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
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

  test "show renders every tab in Fd::ChannelsController::TABS" do
    Fd::ChannelsController::TABS.each do |tab|
      get fd_channel_path(@id, tab: tab)
      assert_response :success, "#{tab} did not return success"
    end
  end

  test "show with unknown tab renders the first tab with Guards" do
    get fd_channel_path(@id, tab: "sideways")

    assert_response :success
    assert_match(/Guards/, response.body)
  end

  test "create readonly adds only that kind and destroy removes it" do
    post_guard("readonly")

    assert live("readonly")
    assert_nil live("bot_allowlist")

    delete fd_channel_guard_path(@id, "readonly")
    assert_nil live("readonly")
  end

  test "create readonly with threads param sets threads?" do
    post_guard("readonly", threads: "1")

    assert live("readonly").threads?
  end

  test "create readonly without threads param leaves threads? false" do
    post_guard("readonly")

    assert_not live("readonly").threads?
  end

  test "update readonly with threads param sets threads? and writes a tuned audit entry" do
    post_guard("readonly")
    patch_guard("readonly", threads: "1")

    assert live("readonly").threads?
    assert_equal 1, Fd::AuditEntry.where(entity_type: "channel_guard", verb: "tuned").count
  end

  test "all four guard kinds can be live on one channel" do
    Fd::ChannelGuard::KINDS.each do |kind|
      guard!(kind, seconds: 30, min_age_days: 7)
    end

    assert_equal 4, Fd::ChannelGuard.live.where(channel_id: @id).count
  end

  test "create with unknown kind adds no guard and alerts" do
    post_guard("sideways")

    assert_equal 0, Fd::ChannelGuard.live.where(channel_id: @id).count
    assert_match(/not a valid guard kind/, flash[:alert])
  end

  test "create slowmode stores seconds and threads params" do
    post_guard("slowmode", seconds: "45", threads: "1")
    guard = live("slowmode")

    assert_equal 45, guard.seconds
    assert guard.threads?
  end

  test "create slowmode without threads param leaves threads? false" do
    post_guard("slowmode", seconds: "45")

    assert_not live("slowmode").threads?
  end

  test "create slowmode without seconds uses DEFAULT_SLOWMODE_SECONDS and no alert" do
    post_guard("slowmode")

    assert_equal Fd::ChannelGuard::DEFAULT_SLOWMODE_SECONDS, live("slowmode").seconds
    assert_nil flash[:alert]
  end

  test "create account_age without min_age_days uses DEFAULT_ACCOUNT_AGE_DAYS and no alert" do
    post_guard("account_age")

    assert_equal Fd::ChannelGuard::DEFAULT_ACCOUNT_AGE_DAYS, live("account_age").min_age_days
    assert_nil flash[:alert]
  end

  test "create slowmode with seconds outside 1 to 3600 adds no guard and alerts" do
    post_guard("slowmode", seconds: "0")
    assert_nil live("slowmode")

    post_guard("slowmode", seconds: "99999")
    assert_nil live("slowmode")
    assert_equal "Enter 1 to 3600 seconds", flash[:alert]
  end

  test "create slowmode with blank reason adds no guard and alerts" do
    post_guard("slowmode", reason: " ")

    assert_nil live("slowmode")
    assert_equal "Enter a reason", flash[:alert]
  end

  test "create slowmode with an end sets expires_at reason and notice_wanted" do
    ends = 2.days.from_now.utc.change(hour: 14, min: 30)

    post_guard("slowmode", expires_on: ends.to_date.to_s, expires_time: "14:30")
    guard = live("slowmode")

    assert_equal ends, guard.expires_at
    assert_equal "Heated argument", guard.reason
    assert guard.notice_wanted
    assert_equal "Slow mode enabled · ends #{Fd::ShortDate.ending(ends)}", flash[:notice]
  end

  test "create slowmode without an end sets no expires_at and notices no end date" do
    post_guard("slowmode")

    assert_nil live("slowmode").expires_at
    assert_equal "Slow mode enabled · no end date", flash[:notice]
  end

  test "create slowmode with a date only ends at the end of that day in utc" do
    day = 2.days.from_now.utc.to_date

    post_guard("slowmode", expires_on: day.to_s)

    assert_equal day.end_of_day.utc.floor(6), live("slowmode").expires_at
  end

  test "create slowmode with a time but no date adds no guard and alerts" do
    post_guard("slowmode", expires_time: "14:30")

    assert_nil live("slowmode")
    assert_equal "Enter a date for the end time", flash[:alert]
  end

  test "create slowmode with an end in the past adds no guard and alerts" do
    post_guard("slowmode", expires_on: 1.day.ago.to_date.to_s)

    assert_nil live("slowmode")
    assert_equal "End must be in the future", flash[:alert]
  end

  test "update slowmode sets the new end and writes an extended audit entry" do
    post_guard("slowmode", expires_on: 1.day.from_now.to_date.to_s, expires_time: "10:00")
    first_end = live("slowmode").expires_at
    ends = 3.days.from_now.utc.change(hour: 9, min: 0)
    patch_guard("slowmode", expires_on: ends.to_date.to_s, expires_time: "09:00")

    assert_equal ends, live("slowmode").expires_at
    extended = Fd::AuditEntry.where(entity_type: "channel_guard", verb: "extended").sole
    assert_equal first_end.iso8601, extended.before["expires_at"]
  end

  test "update slowmode can move the end earlier or give a guard without an end one" do
    post_guard("slowmode", expires_on: 5.days.from_now.to_date.to_s, expires_time: "10:00")
    earlier = 1.day.from_now.utc.change(hour: 9, min: 0)
    patch_guard("slowmode", expires_on: earlier.to_date.to_s, expires_time: "09:00")
    assert_equal earlier, live("slowmode").expires_at

    Fd::ChannelGuard.live_for(@id, kind: "slowmode").update!(expires_at: nil)
    patch_guard("slowmode", expires_on: earlier.to_date.to_s, expires_time: "09:00")
    assert_equal earlier, live("slowmode").expires_at
  end

  test "update slowmode without a date alerts" do
    post_guard("slowmode", expires_on: 1.day.from_now.to_date.to_s)
    patch_guard("slowmode")

    assert_equal "Enter the end date", flash[:alert]
  end

  test "create slowmode after destroy leaves allows empty" do
    post_guard("slowmode")
    post fd_channel_allows_path(@id, "slowmode"), params: { subject_ids: ["USLOW"] }
    delete fd_channel_guard_path(@id, "slowmode")
    assert_equal "Slow mode disabled", flash[:notice]
    post_guard("slowmode")

    assert_empty live("slowmode").allows
  end

  test "slow mode tab shows time left with extend and disable" do
    post_guard("slowmode", expires_on: 2.days.from_now.to_date.to_s, expires_time: "10:00", threads: "1")

    get fd_channel_path(@id, tab: "slowmode")

    assert_select ".setline .setval", /\Ain \d+d \d+h · /
    assert_select ".setline .setval", "Included"
    assert_select "[data-modal-id-value=slowmode-extend] input[name=expires_on][required]"
    assert_select "[data-modal-id-value=slowmode-extend] input[name=expires_time]"
    assert_select "form[action=?] button", fd_channel_guard_path(@id, "slowmode"), text: "Disable"
  end

  test "slow mode tab when off offers the enable dialog with no end by default" do
    get fd_channel_path(@id, tab: "slowmode")

    assert_select ".empty-title", "Off"
    assert_select "[data-modal-id-value=slowmode-enable] input[name=expires_on]:not([required])"
    assert_select "[data-modal-id-value=slowmode-enable] input[name=expires_time]"
  end

  test "create readonly leaves notice_wanted false" do
    post_guard("readonly")

    assert_not live("readonly").notice_wanted
  end

  test "create account_age stores min_age_days" do
    post_guard("account_age", min_age_days: "7")

    assert_equal 7, live("account_age").min_age_days
  end

  test "create account_age with min_age_days outside 1 to 365 adds no guard and alerts" do
    post_guard("account_age", min_age_days: "0")

    assert_nil live("account_age")
    assert_match(/Enter 1 to 365 days/, flash[:alert])
  end

  test "update on a kind with no live guard alerts" do
    patch_guard("slowmode", seconds: "30")

    assert_match(/not guarded that way/, flash[:alert])
  end

  test "create allow on readonly stores the subject_ids" do
    guard!("readonly")
    post fd_channel_allows_path(@id, "readonly"), params: { subject_ids: ["USOMEBODY"] }

    assert_equal ["USOMEBODY"], live("readonly").allows.pluck(:subject_id)
  end

  test "create allow on readonly adds the allow to that kind only" do
    guard!("readonly")
    guard!("slowmode", seconds: 30)
    post fd_channel_allows_path(@id, "readonly"), params: { subject_ids: ["USOMEBODY"] }

    assert_equal 1, live("readonly").allows.count
    assert_equal 0, live("slowmode").allows.count
  end

  test "create allow on account_age stores the subject and redirects to its tab" do
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

  test "create account_age after destroy restores allows" do
    post_guard("account_age")
    post fd_channel_allows_path(@id, "account_age"), params: { subject_ids: ["USOMEBODY"] }
    delete fd_channel_guard_path(@id, "account_age")
    post_guard("account_age")

    assert_equal ["USOMEBODY"], live("account_age").allows.pluck(:subject_id)
  end

  test "create allow on a kind with no live guard alerts" do
    post fd_channel_allows_path(@id, "readonly"), params: { subject_ids: ["USOMEBODY"] }

    assert_match(/not guarded/, flash[:alert])
  end

  test "create readonly after destroy restores allows with notice and audit entries" do
    post_guard("readonly")
    post fd_channel_allows_path(@id, "readonly"), params: { subject_ids: ["USOMEBODY", "UOTHER"] }
    delete fd_channel_guard_path(@id, "readonly")
    post_guard("readonly")

    guard = live("readonly")
    assert_equal ["UOTHER", "USOMEBODY"], guard.allows.pluck(:subject_id).sort
    assert_equal "Read-only turned on · 2 allowed restored", flash[:notice]
    restored = Fd::AuditEntry.where(entity_type: "channel_allow", entity_id: guard.id, verb: "added")
    assert_equal 2, restored.count
  end

  test "create bot_allowlist after destroy restores added_by on allows" do
    post_guard("bot_allowlist")
    post fd_channel_allows_path(@id, "bot_allowlist"), params: { subject_ids: ["B0BOT"] }
    delete fd_channel_guard_path(@id, "bot_allowlist")
    post_guard("bot_allowlist")

    assert_equal ["UME"], live("bot_allowlist").allows.pluck(:added_by)
  end

  test "create readonly for the first time leaves allows empty" do
    post_guard("readonly")

    assert_empty live("readonly").allows
    assert_equal "Read-only turned on", flash[:notice]
  end

  test "create restores allows only from the same kind" do
    post_guard("slowmode")
    post fd_channel_allows_path(@id, "slowmode"), params: { subject_ids: ["USLOW"] }
    delete fd_channel_guard_path(@id, "slowmode")
    post_guard("readonly")

    assert_empty live("readonly").allows
  end

  test "overview tab lists every guard kind label" do
    get fd_channel_path(@id, tab: "overview")

    assert_match(/Bot allow list/, response.body)
    assert_match(/Read-only/, response.body)
    assert_match(/Slow mode/, response.body)
    assert_match(/New accounts/, response.body)
  end

  test "kind tabs render only their own guard events" do
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

  test "readonly tab renders events after the guard is destroyed" do
    guard = guard!("readonly")
    Fd::ChannelGuardEvent.create!(guard_id: guard.id, channel_id: @id,
      subject_id: "USOMEBODY", verb: "deleted")
    delete fd_channel_guard_path(@id, "readonly")
    get fd_channel_path(@id, tab: "readonly")

    assert_match(/USOMEBODY/, response.body)
  end

  test "readonly tab without events renders no Activity card" do
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

  def queued_kicks
    ActiveRecord::Base.connection.select_rows(
      "SELECT channel_id, subject_id FROM fd.bot_kicks WHERE channel_id = #{ActiveRecord::Base.connection.quote(@id)}"
    )
  end

  test "removing a bot from a live allow list queues a kick" do
    guard!("bot_allowlist").allows.create!(subject_id: "B0BOT", added_by: "UME")

    delete fd_channel_allow_path(@id, "bot_allowlist", "B0BOT")

    assert_equal [[@id, "B0BOT"]], queued_kicks
  end

  test "removing an exemption queues no kick" do
    guard!("slowmode", seconds: 30).allows.create!(subject_id: "USLOW", added_by: "UME")

    delete fd_channel_allow_path(@id, "slowmode", "USLOW")

    assert_empty queued_kicks
  end

  test "create without channel.guard adds no guard" do
    revoke_roles!("UME")
    grant_role!("UME", "gardener")
    post_guard("readonly")

    assert_equal 0, Fd::ChannelGuard.live.where(channel_id: @id).count
  end
end

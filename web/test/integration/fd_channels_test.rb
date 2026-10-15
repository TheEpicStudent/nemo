require "test_helper"

class FdChannelsTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    @channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    skip "the corpus has no channel" if @channel.nil?
  end

  def guard!
    Fd::ChannelGuard.create!(kind: Fd::ChannelGuard::BOT_ALLOWLIST,
      channel_id: @channel.channel_id, opened_by: "UME")
  end

  test "a channel nobody guards still opens" do
    get fd_channel_path(@channel.channel_id)

    assert_response :success
  end

  test "a guarded channel opens with its allow list" do
    guard!.allows.create!(subject_id: "B0CACHET", label: "Cachet", added_by: "UME")

    get fd_channel_path(@channel.channel_id)

    assert_response :success
  end

  def seat_nemo!(inside)
    ActiveRecord::Base.connection.execute(
      "INSERT INTO fd.channel_membership (channel_id, inside) " \
      "VALUES (#{ActiveRecord::Base.connection.quote(@channel.channel_id)}, #{inside}) " \
      "ON CONFLICT (channel_id) DO UPDATE SET inside = EXCLUDED.inside"
    )
  end

  def record_join!(verb, why = nil, at: Time.current)
    connection = ActiveRecord::Base.connection
    connection.execute(
      "INSERT INTO fd.channel_joins (channel_id, verb, why, at) VALUES " \
      "(#{connection.quote(@channel.channel_id)}, #{connection.quote(verb)}, " \
      "#{connection.quote(why)}, #{connection.quote(at)})"
    )
  end

  test "the channel page warns when nemo is not in the channel" do
    seat_nemo!(false)

    get fd_channel_path(@channel.channel_id)

    assert_select "p.sev-crit", "Nemo is not in the channel"
  end

  test "the channel page asks for an invite when a private channel refused nemo" do
    seat_nemo!(false)
    record_join!("refused", FdChannelsHelper::NEEDS_INVITE)

    get fd_channel_path(@channel.channel_id)

    assert_select "p.sev-crit", "Nemo isn't in this private channel, someone has to /invite it"
  end

  test "the channel page says when nemo was removed" do
    record_join!("joined", at: 1.hour.ago)
    record_join!("left")

    get fd_channel_path(@channel.channel_id)

    assert_select "p.sev-crit", "Nemo was taken out of here"
  end

  test "the channel page shows no warning when nemo is in the channel" do
    seat_nemo!(true)

    get fd_channel_path(@channel.channel_id)

    assert_select "p.sev-crit", count: 0
    assert_select "p.sev-warn", count: 0
  end

  test "a channel we have never heard of does not raise" do
    get fd_channel_path("C0NOTHING")

    assert_response :success
  end

  test "a signed out visitor cannot read the channels" do
    reset!
    get fd_channels_path

    assert_redirected_to login_path
  end

  test "turning the guard on records who did it" do
    post fd_channel_guard_path(@channel.channel_id, "bot_allowlist")

    guard = Fd::ChannelGuard.live_for(@channel.channel_id)
    assert_not_nil guard
    assert_equal "UME", guard.opened_by
    assert Fd::AuditEntry.where(entity_type: "channel_guard", entity_id: guard.id,
      verb: "opened").exists?
  end

  test "a channel cannot be guarded twice" do
    guard!

    assert_no_difference -> { Fd::ChannelGuard.count } do
      post fd_channel_guard_path(@channel.channel_id, "bot_allowlist")
    end
  end

  test "lifting keeps the allow list and the guard row" do
    guard = guard!
    guard.allows.create!(subject_id: "B0CACHET", added_by: "UME")

    delete fd_channel_guard_path(@channel.channel_id, "bot_allowlist")

    assert_nil Fd::ChannelGuard.live_for(@channel.channel_id)
    assert_equal "lifted", guard.reload.state
    assert_equal "UME", guard.lifted_by
    assert_not_nil guard.lifted_at
    assert_equal 1, guard.allows.count
  end

  test "lifting a channel nobody guards changes nothing" do
    delete fd_channel_guard_path(@channel.channel_id, "bot_allowlist")

    assert_equal 0, Fd::ChannelGuard.where(channel_id: @channel.channel_id).count
  end

  test "allowing a bot records who vouched for it" do
    guard = guard!

    post fd_channel_allows_path(@channel.channel_id, "bot_allowlist"),
      params: { subject_ids: ["B0CACHET"] }

    allow = guard.allows.find_by(subject_id: "B0CACHET")
    assert_not_nil allow
    assert_equal "UME", allow.added_by
    assert Fd::AuditEntry.where(entity_type: "channel_allow", entity_id: guard.id,
      verb: "added").exists?
  end

  test "allowing the same bot twice leaves one row" do
    guard = guard!
    2.times do
      post fd_channel_allows_path(@channel.channel_id, "bot_allowlist"), params: { subject_ids: ["B0CACHET"] }
    end

    assert_equal 1, guard.allows.where(subject_id: "B0CACHET").count
  end

  test "an id that is not a member id is refused" do
    guard = guard!

    post fd_channel_allows_path(@channel.channel_id, "bot_allowlist"), params: { subject_ids: ["not-an-id"] }

    assert_equal 0, guard.allows.count
  end

  test "nothing can be allowed on a channel nobody guards" do
    post fd_channel_allows_path(@channel.channel_id, "bot_allowlist"), params: { subject_ids: ["B0CACHET"] }

    assert_equal 0, Fd::ChannelGuardAllow.count
  end

  test "removing a bot takes it off the list and lands in the trail" do
    guard = guard!
    guard.allows.create!(subject_id: "B0CACHET", label: "Cachet", added_by: "UME")

    delete fd_channel_allow_path(@channel.channel_id, "bot_allowlist", "B0CACHET")

    assert_equal 0, guard.allows.count
    assert Fd::AuditEntry.where(entity_type: "channel_allow", entity_id: guard.id,
      verb: "removed").exists?
  end

  test "the bot picker looks for bots, the member picker does not" do
    bot = Fd::Member.live.where(is_bot: false).first
    skip "the corpus has no member" if bot.nil?

    user_ids = Fd::MemberFinder.new(bot.name).suggest(limit: Fd::Member::LIMIT, bots: true)
    assert_not_includes user_ids, bot.user_id
  end

  test "what the guard did survives the guard being lifted" do
    guard = guard!
    guard.events.create!(channel_id: @channel.channel_id, subject_id: "B0ZAPIER", verb: "kicked")

    delete fd_channel_guard_path(@channel.channel_id, "bot_allowlist")
    get fd_channel_path(@channel.channel_id)

    assert_response :success
    assert_equal 1, Fd::ChannelGuardEvent.where(channel_id: @channel.channel_id).count
  end

  test "somebody without channel.guard cannot turn one on" do
    firefighter = hold_role!("UFF9", "firefighter")
    move_capability!("firefighter", "channel.guard", false, by: "UME")
    sign_in_as(firefighter)

    post fd_channel_guard_path(@channel.channel_id, "bot_allowlist")

    assert_nil Fd::ChannelGuard.live_for(@channel.channel_id)
  end
end

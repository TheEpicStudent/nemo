require "test_helper"

class CommunityAccessTest < ActionDispatch::IntegrationTest
  setup do
    @manager = grant_role!("UCABOSS", "community_manager")
  end

  def account_without_grants
    Account.create!(user_id: "UCANONE")
  end

  def scoped(name, *keys)
    staff = Account.find_or_create_by!(user_id: "UCA#{name.upcase}")
    keys.each do |key|
      Authz::Grant.grant!(staff.user_id, kind: "capability", name: key, by: "test")
    end
    Current.forget_roles
    staff
  end

  def reads_names
    scoped("names", "member.read")
  end

  test "root without any grant returns success" do
    sign_in_as(account_without_grants)

    get root_path

    assert_response :success
  end

  test "fd root without any grant redirects to root with an access alert" do
    sign_in_as(account_without_grants)

    get fd_root_path

    assert_redirected_to root_path
    assert_match(/Fire Engine access required/, flash[:alert])
  end

  test "root without a Fire Engine grant returns success" do
    sign_in_as(account_without_grants)

    get root_path

    assert_response :success
  end

  test "engine path without any grant redirects to root" do
    sign_in_as(account_without_grants)

    get engine_path

    assert_redirected_to root_path
  end

  test "firefighter has channel.all and lacks engine.manage and analytics.member.read" do
    firefighter = grant_role!("UCAFF", "firefighter")

    assert Authz.holds?(firefighter, "channel.all"), "firefighter holds channel.all by default"
    assert Community::Access.allow?(firefighter, "analytics.channel.read")
    refute Authz.holds?(firefighter, "engine.manage"), "firefighter lacks engine.manage"
    assert Community::Access.allow?(firefighter, "analytics.workspace.read"),
      "analytics.workspace.read is allowed for every signed-in member"
    assert_not Community::Access.allow?(firefighter, "analytics.member.read")
  end

  test "community_manager is allowed ops.engine and channel.all with no capability grants" do
    assert Community::Access.allow?(@manager, "ops.engine")
    assert Authz.holds?(@manager, "channel.all")
    assert_equal 0, Authz::Grant.live.for_person(@manager.user_id).capabilities.count,
      "community_manager has no capability grant rows"
  end

  test "gardener with a channel.backfill grant keeps the role and gains only that capability" do
    staff = grant_role!("UCABOTH", "gardener")
    Authz::Grant.grant!(staff.user_id, kind: "capability", name: "channel.backfill", by: "test")
    Current.forget_roles

    assert_equal %w[gardener], Authz.effective_roles(staff.user_id)
    assert Community::Access.allow?(staff, "ops.channel.backfill"), "capability grant allows ops.channel.backfill"
    assert_not Community::Access.allow?(staff, "analytics.member.read"),
      "capability grant does not allow analytics.member.read"
  end

  def some_channels(count = 3)
    Analytics::DimChannel.where(archived: false).order(:channel_id).limit(count).to_a
  end

  def set_audience(channel, audience)
    Channels::Audience::Setting.create!(channel_id: channel.channel_id,
      audience: audience, set_by: @manager.user_id)
  end

  test "Audience.for returns everyone channels and excludes shared channels" do
    visible, hidden, = some_channels
    set_audience(visible, "everyone")
    set_audience(hidden, "shared")
    staff = account_without_grants

    ids = Channels::Audience.for(staff).pluck(:channel_id)

    assert_includes ids, visible.channel_id
    assert_not_includes ids, hidden.channel_id, "shared audience channel is excluded"
  end

  test "Audience.for returns appointed and everyone channels for a promethean only" do
    public_one, appointed, other = some_channels
    set_audience(public_one, "everyone")
    staff = Account.create!(user_id: "UCAPROM")
    Prometheus::Appointment.insert_all!([
      { user_id: staff.user_id, channel_id: appointed.channel_id, role: "manager",
        seen_at: Time.current }
    ])
    Current.forget_roles

    ids = Channels::Audience.for(staff).pluck(:channel_id)

    assert_equal %w[promethean], Authz.effective_roles(staff.user_id), "appointment grants the promethean role"
    assert_includes ids, appointed.channel_id, "appointed channel is included"
    assert_includes ids, public_one.channel_id, "everyone audience channel is included"
    assert_not_includes ids, other.channel_id
  end

  test "Audience.for includes a channel with an Audience::Grant row" do
    _open, granted, = some_channels
    staff = account_without_grants
    Channels::Audience::Grant.create!(user_id: staff.user_id, channel_id: granted.channel_id,
      granted_by: @manager.user_id, granted_at: Time.current)
    Current.forget_roles

    ids = Channels::Audience.for(staff).pluck(:channel_id)

    assert_includes ids, granted.channel_id
  end

  test "show for channel outside the audience redirects to channels list with alert" do
    hidden = some_channels(1).first
    sign_in_as(reads_names)

    get channel_path(hidden.channel_id)

    assert_redirected_to channels_path(q: hidden.channel_id)
    assert_match(/Channel not shared/, flash[:alert])
  end

  test "channels index with scope all and a filter param returns success" do
    sign_in_as(reads_names)

    get channels_path(scope: "all", f: ["never_posted"])

    assert_response :success
  end

  test "active journey without member.read returns success" do
    sign_in_as(account_without_grants)

    get active_journey_path

    assert_response :success
  end

  test "active journey with member.read returns success" do
    sign_in_as(reads_names)

    get active_journey_path

    assert_response :success
  end

  def backfiller
    scoped("backfill", "channel.read", "channel.backfill")
  end

  def priceable_channel
    Analytics::DimChannel.where(archived: false).order(:channel_id).find do |channel|
      ChannelBackfill.estimate(channel).to_i.positive?
    end
  end

  test "opt_in as gardener creates no ChannelBackfill and alerts community manager only" do
    channel = some_channels(1).first
    set_audience(channel, "everyone")
    sign_in_as(grant_role!("UCAREADER", "gardener"))

    assert_no_difference -> { ChannelBackfill.count } do
      post opt_in_channel_path(channel.channel_id)
    end

    assert_match(/Community manager only/, flash[:alert])
  end

  test "opt_in with channel.backfill over the ceiling creates no row and requires engine.manage" do
    channel = priceable_channel
    skip "the seed priced no channel" if channel.nil?
    set_audience(channel, "everyone")
    Engine::Setting.set!("engine", "backfill_ceiling", "0", by: @manager.user_id)
    sign_in_as(backfiller)

    assert_no_difference -> { ChannelBackfill.count } do
      post opt_in_channel_path(channel.channel_id)
    end

    assert_match(/requires engine.manage/, flash[:alert])
  end

  test "engine.manage grant raises and community_manager opt_in ignores backfill_ceiling" do
    channel = priceable_channel
    skip "the seed priced no channel" if channel.nil?
    set_audience(channel, "everyone")
    Engine::Setting.set!("engine", "backfill_ceiling", "0", by: @manager.user_id)

    assert_raises(Authz::Grant::NotAllowedError) do
      Authz::Grant.grant!("UCASYNC", kind: "capability", name: "engine.manage", by: "test")
    end

    sign_in_as(@manager)
    assert_difference -> { ChannelBackfill.count }, 1 do
      post opt_in_channel_path(channel.channel_id)
    end
  end

  test "joining journey links newcomer channels only when Audience.may_see? is true" do
    sign_in_as(account_without_grants)

    get joining_journey_path
    assert_response :success

    Analytics::MartNewcomerChannels
      .ranked(Analytics::MartNewcomerChannels::DEFAULT_MEASURE, floor: HomeHelper::MIN_SAMPLE)
      .each do |row|
        next if Channels::Audience.may_see?(Current.staff, row.channel_id)

        refute_match %r{href="/channels/#{row.channel_id}"}, response.body,
          "#{row.channel_id} links to statistics without audience access"
      end
  end

  test "channels index renders Channels activity without a channel grant" do
    sign_in_as(reads_names)
    get channels_path
    assert_response :success
    assert_match "Channels activity", response.body,
      "Channels activity renders without a channel grant"

    sign_in_as(grant_role!("UCABANDS", "analytics"))
    get channels_path
    assert_response :success
    assert_match "Channels activity", response.body
  end

  test "role change replaces the previous role and keeps capability grants" do
    staff = grant_role!("UCASWAP", "firefighter")
    Authz::Grant.grant!(staff.user_id, kind: "capability", name: "channel.backfill", by: "test")
    grant_role!("UCASWAP", "gardener")
    Current.forget_roles

    assert_equal %w[gardener], Authz.effective_roles(staff.user_id),
      "second role replaces the first role"
    assert_equal %w[channel.backfill],
      Authz::Grant.live.for_person(staff.user_id).capabilities.pluck(:name),
      "role change keeps capability grants"
  end

  test "Community::Access::CAPABILITY values are all declared capabilities" do
    refute_empty Community::Access::CAPABILITY

    unknown = Community::Access::CAPABILITY.reject { |_key, capability|
      Authz.keys.include?(capability)
    }

    assert_empty unknown, "these permissions name capabilities that do not exist: #{unknown.inspect}"
  end

  test "may_community? keys used in views and app code are all mapped in Community::Access" do
    requested_keys = Dir[Rails.root.join("app/views/**/*.erb"), Rails.root.join("app/**/*.rb")]
      .flat_map { |path| File.read(path).scan(/may_community\?\(?\s*["']([\w.]+)["']/) }
      .flatten.uniq

    refute_empty requested_keys, "no may_community? calls found"

    unmapped = requested_keys.reject { |key|
      key == Community::Access::EVERY_ACCOUNT || Community::Access::CAPABILITY.key?(key)
    }

    assert_empty unmapped, "these permission keys are requested but not mapped: #{unmapped.inspect}"
  end
end

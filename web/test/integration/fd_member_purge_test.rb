require "test_helper"

class FdMemberPurgeTest < ActionDispatch::IntegrationTest
  MEMBER = "UDEAC0001".freeze

  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def deactivate(**over)
    post fd_member_guards_path(MEMBER),
      params: { kind: Fd::MemberGuard::DEACTIVATION, reason: "a raid" }.merge(over)
  end

  def purges = Fd::ChannelPurge.where(member_id: MEMBER)

  def guard = Fd::MemberGuard.where(subject_id: MEMBER).sole

  test "create deactivation with purge_messages queues all-channel purge for the guard" do
    deactivate(purge_messages: "1")
    purge = purges.sole

    assert_equal [nil, nil, "deactivation", guard.id, "asked", "a raid"],
      [purge.channel_id, purge.wanted, purge.source, purge.guard_id, purge.state, purge.reason]
    assert_match(/Message purge queued/, flash[:notice])
    assert_equal 1, Fd::AuditEntry.where(entity_type: "member_purge", verb: "queued").count
  end

  test "create deactivation without purge_messages creates no purge" do
    deactivate

    assert guard
    assert_equal 0, purges.count
    assert_no_match(/purged/, flash[:notice])
  end

  test "member page renders purge_messages checkbox with member.purge" do
    get fd_member_path(MEMBER)

    assert_select %(input[name="purge_messages"][type="checkbox"])
    assert_match(/Purge all messages/, response.body)
  end

  test "member page without member.purge renders no purge_messages input" do
    override_capability!("community_manager", "member.purge", false)
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    override_capability!("firefighter", "member.purge", false)
    get fd_member_path(MEMBER)

    assert_select %(input[name="purge_messages"]), count: 0
  end

  test "create deactivation with purge_messages without member.purge creates no purge or guard" do
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    override_capability!("firefighter", "member.purge", false)
    deactivate(purge_messages: "1")

    assert_equal 0, purges.count
    assert_equal 0, Fd::MemberGuard.where(subject_id: MEMBER).count
  end

  test "create deactivation with an existing asked purge creates no second purge" do
    Fd::ChannelPurge.create!(member_id: MEMBER, state: "asked", source: "slack", asked_by: "UME")
    deactivate(purge_messages: "1")

    assert_equal 1, purges.count
    assert guard
    assert_match(/Message purge already running/, flash[:notice])
  end

  test "member page purges tab lists purges with progress and links" do
    all_channels_purge = Fd::ChannelPurge.create!(member_id: MEMBER, state: "running", source: "deactivation",
      asked_by: "UME", found: 40, purged: 12)
    channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    channel_purge = Fd::ChannelPurge.create!(member_id: MEMBER, channel_id: channel.channel_id, wanted: 5,
      state: "done", asked_by: "UME", purged: 5, finished_at: Time.current, left_after_check: 0)
    get fd_member_path(MEMBER, tab: "purges")

    assert_response :success
    assert_match(/All channels/, response.body)
    assert_match(/12 of 40 purged/, response.body)
    assert_match(/0 left after the check/, response.body)
    assert_match(%r{href="#{fd_member_purge_path(MEMBER, all_channels_purge)}"}, response.body)
    assert_match(%r{href="#{fd_channel_purge_path(channel.channel_id, channel_purge)}"}, response.body)
  end

  test "member purge show renders items for an all-channel purge" do
    channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    purge = Fd::ChannelPurge.create!(member_id: MEMBER, state: "done", source: "deactivation",
      asked_by: "UME", purged: 1, finished_at: Time.current, left_after_check: 0)
    Fd::PurgeItem.create!(purge_id: purge.id, channel_id: channel.channel_id, ts: "1700000000.000100",
      author_id: MEMBER, text: "the raid", state: "deleted", done_at: Time.current)
    get fd_member_purge_path(MEMBER, purge)

    assert_response :success
    assert_match(/Purged from/, response.body)
    assert_match(/in every channel/, response.body)
    assert_match(/the raid/, response.body)
    assert_match(/in ##{Regexp.escape(channel.name)}/, response.body) if channel.name.present?
    assert_includes response.body, %(href="#{fd_member_path(MEMBER, tab: "purges")}")
  end

  test "member purge show for another member purge returns 404" do
    purge = Fd::ChannelPurge.create!(member_id: "UOTHER001", state: "asked", asked_by: "UME")
    get fd_member_purge_path(MEMBER, purge)

    assert_response :not_found
  end

  test "member page purges tab without member.purge omits Purges tab" do
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    override_capability!("firefighter", "member.purge", false)
    get fd_member_path(MEMBER, tab: "purges")

    assert_no_match(/>Purges</, response.body)
  end
end

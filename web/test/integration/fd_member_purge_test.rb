require "test_helper"

class FdMemberPurgeTest < ActionDispatch::IntegrationTest
  MEMBER = "UDEAC0001".freeze

  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def deactivate(**over)
    post fd_member_guards_path(MEMBER),
      params: { kind: Fd::MemberGuard::DEACTIVATION, reason: "a raid" }.merge(over)
  end

  def purges = Fd::ChannelPurge.where(member_id: MEMBER)

  def guard = Fd::MemberGuard.where(subject_id: MEMBER).sole

  test "ticking purge all messages queues a purge of every message, tied to the deactivation" do
    deactivate(purge_messages: "1")
    one = purges.sole

    assert_equal [nil, nil, "deactivation", guard.id, "asked", "a raid"],
      [one.channel_id, one.wanted, one.source, one.guard_id, one.state, one.reason]
    assert_match(/All their messages are purged once it goes through/, flash[:notice])
    assert_equal 1, Fd::AuditEntry.where(entity_type: "member_purge", verb: "queued").count
  end

  test "leaving it unticked purges nothing" do
    deactivate

    assert guard
    assert_equal 0, purges.count
    assert_no_match(/purged/, flash[:notice])
  end

  test "the tickbox is offered to who may purge" do
    get fd_member_path(MEMBER)

    assert_select %(input[name="purge_messages"][type="checkbox"])
    assert_match(/Purge all messages/, response.body)
  end

  test "the tickbox is not offered to who may not purge" do
    move_capability!("community_manager", "member.purge", false)
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    move_capability!("firefighter", "member.purge", false)
    get fd_member_path(MEMBER)

    assert_select %(input[name="purge_messages"]), count: 0
  end

  test "somebody who may not purge cannot send the tickbox anyway" do
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    move_capability!("firefighter", "member.purge", false)
    deactivate(purge_messages: "1")

    assert_equal 0, purges.count
    assert_equal 0, Fd::MemberGuard.where(subject_id: MEMBER).count
  end

  test "a purge of theirs already waiting is not doubled" do
    Fd::ChannelPurge.create!(member_id: MEMBER, state: "asked", source: "slack", asked_by: "UME")
    deactivate(purge_messages: "1")

    assert_equal 1, purges.count
    assert guard
    assert_match(/A purge of their messages is already running/, flash[:notice])
  end

  test "the member page lists their purges" do
    everywhere = Fd::ChannelPurge.create!(member_id: MEMBER, state: "running", source: "deactivation",
      asked_by: "UME", found: 40, purged: 12)
    channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    here = Fd::ChannelPurge.create!(member_id: MEMBER, channel_id: channel.channel_id, wanted: 5,
      state: "done", asked_by: "UME", purged: 5, finished_at: Time.current, left_after_check: 0)
    get fd_member_path(MEMBER, tab: "purges")

    assert_response :success
    assert_match(/Every channel/, response.body)
    assert_match(/12 of 40 purged/, response.body)
    assert_match(/0 left after the check/, response.body)
    assert_match(%r{href="#{fd_member_purge_path(MEMBER, everywhere)}"}, response.body)
    assert_match(%r{href="#{fd_channel_purge_path(channel.channel_id, here)}"}, response.body)
  end

  test "a purge across every channel opens its own page with each message's channel" do
    channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    one = Fd::ChannelPurge.create!(member_id: MEMBER, state: "done", source: "deactivation",
      asked_by: "UME", purged: 1, finished_at: Time.current, left_after_check: 0)
    Fd::PurgeItem.create!(purge_id: one.id, channel_id: channel.channel_id, ts: "1700000000.000100",
      author_id: MEMBER, text: "the raid", state: "deleted", done_at: Time.current)
    get fd_member_purge_path(MEMBER, one)

    assert_response :success
    assert_match(/Purged from/, response.body)
    assert_match(/in every channel/, response.body)
    assert_match(/the raid/, response.body)
    assert_match(/in ##{Regexp.escape(channel.name)}/, response.body) if channel.name.present?
    assert_includes response.body, %(href="#{fd_member_path(MEMBER, tab: "purges")}")
  end

  test "a purge of somebody else is not found under this member" do
    one = Fd::ChannelPurge.create!(member_id: "UOTHER001", state: "asked", asked_by: "UME")
    get fd_member_purge_path(MEMBER, one)

    assert_response :not_found
  end

  test "the purges tab needs member purge" do
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    move_capability!("firefighter", "member.purge", false)
    get fd_member_path(MEMBER, tab: "purges")

    assert_no_match(/>Purges</, response.body)
  end
end

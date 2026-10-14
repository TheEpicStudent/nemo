require "test_helper"

class FdChannelPurgeTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    @channel = Analytics::DimChannel.where(archived: false).order(:channel_id).first
    skip "the corpus has no channel" if @channel.nil?
    @id = @channel.channel_id
  end

  def post_purge(**over)
    post fd_channel_purges_path(@id),
      params: { wanted: "10", reason: "a raid" }.merge(over)
  end

  def purges = Fd::ChannelPurge.for_channel(@id)

  def kept!(purge, entries)
    entries.each do |entry|
      Fd::PurgeItem.create!(purge_id: purge.id, channel_id: purge.channel_id, ts: entry["ts"],
        thread_ts: entry["thread_ts"], author_id: entry["user"], text: entry["text"],
        state: "deleted", done_at: Time.current)
    end
  end

  test "the purge tab opens" do
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_match(/Purge/, response.body)
  end

  test "a purge is queued and audited" do
    post_purge
    one = purges.sole

    assert_equal 10, one.wanted
    assert_equal "a raid", one.reason
    assert_equal "asked", one.state
    assert_equal "UME", one.asked_by
    assert_equal 1, Fd::AuditEntry.where(entity_type: "channel_purge", verb: "queued").count
  end

  test "expand than the cap is refused" do
    post_purge(wanted: (Fd::ChannelPurge::MOST + 1).to_s)

    assert_equal 0, purges.count
    assert_match(/from 1 to/, flash[:alert])
  end

  test "none at all is refused" do
    post_purge(wanted: "0")

    assert_equal 0, purges.count
    assert_match(/from 1 to/, flash[:alert])
  end

  test "no reason is refused" do
    post_purge(reason: "  ")

    assert_equal 0, purges.count
    assert_match(/say why/, flash[:alert])
  end

  test "a second purge while one is waiting is refused" do
    post_purge
    post_purge

    assert_equal 1, purges.count
    assert_match(/already running/, flash[:alert])
  end

  test "another purge is allowed once the first is done" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current)
    post_purge

    assert_equal 2, purges.count
  end

  test "the tab shows what was purged" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, purged: 8)
    kept!(purges.sole, [{ "ts" => "1", "user" => "USUB", "text" => "the raid" }])
    get fd_channel_path(@id, tab: "purge")

    assert_match(/a raid/, response.body)
    assert_match(/done/, response.body)
    assert_match(/8 purged/, response.body)
  end

  test "replies purged with a thread are counted apart" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, purged: 4)
    kept!(purges.sole, [
      { "ts" => "1.1", "thread_ts" => "1", "user" => "USUB", "text" => "in it" },
      { "ts" => "1.2", "thread_ts" => "1", "user" => "USUB", "text" => "again" },
      { "ts" => "1", "thread_ts" => nil, "user" => "USUB", "text" => "the top" }
    ])
    get fd_channel_path(@id, tab: "purge")

    assert_equal 2, purges.sole.reply_count
    assert_match(/2 in threads/, response.body)
  end

  def post_member_purge(**over)
    post_purge(**{ kind: "member", member_id: "USUB0001", wanted: "", member_wanted: "" }.merge(over))
  end

  test "everything one member posted here can be asked for" do
    post_member_purge
    one = purges.sole

    assert_equal [@id, "USUB0001", nil], [one.channel_id, one.member_id, one.wanted]
    assert_match(/Purging every message from .+ in this channel/, flash[:notice])
    assert_equal 1, Fd::AuditEntry.where(entity_type: "member_purge", verb: "queued").count
  end

  test "a member purge can take only their last few here" do
    post_member_purge(member_wanted: "30")
    one = purges.sole

    assert_equal ["USUB0001", 30], [one.member_id, one.wanted]
    assert_match(/Purging the last 30 messages from .+ in this channel/, flash[:notice])
  end

  test "a member count out of range is refused" do
    post_member_purge(member_wanted: "0")

    assert_equal 0, purges.count
    assert_match(/or leave it empty for all of theirs/, flash[:alert])
  end

  test "the modal says purge, with no take down left" do
    get fd_channel_path(@id, tab: "purge")

    assert_match(/Purge messages in/, response.body)
    assert_select %(input[type="submit"][value="Purge"])
    assert_select %(input[name="member_wanted"][placeholder="All"])
    assert_no_match(/[Tt]ake (them )?down/, response.body)
  end

  test "a member purge needs the member picked" do
    post_member_purge(member_id: "")

    assert_equal 0, purges.count
    assert_match(/pick the member/, flash[:alert])
  end

  test "there is no way to ask for every message in the channel" do
    post_purge(wanted: "", every: "1")

    assert_equal 0, purges.count
    assert_match(/from 1 to/, flash[:alert])
  end

  test "a member purge and a channel purge may wait side by side" do
    post_purge
    post_member_purge

    assert_equal 2, purges.count
  end

  test "the same member cannot be purged twice at once" do
    post_member_purge
    post_member_purge

    assert_equal 1, purges.count
    assert_match(/already running/, flash[:alert])
  end

  test "a big number is fine up to the cap" do
    post_purge(wanted: "2500")

    assert_equal 2500, purges.sole.wanted
    assert_equal "Purging the last 2,500 messages in this channel", flash[:notice]
  end

  test "a running purge shows how far it has got" do
    post_member_purge
    purges.sole.update!(state: "running", started_at: Time.current, found: 1204, purged: 120)
    get fd_channel_path(@id, tab: "purge")

    assert_match(/Every message/, response.body)
    assert_match(/120 of 1,204 purged/, response.body)
  end

  test "a finished purge shows what the check found" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, purged: 10,
      left_after_check: 0, checked_at: Time.current)
    get fd_channel_path(@id, tab: "purge")

    assert_match(/Last 10/, response.body)
    assert_match(/0 left after the check/, response.body)
  end

  test "a check that could not run says so" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, purged: 10,
      error: "the check could not run: search is down")
    get fd_channel_path(@id, tab: "purge")

    assert_match(/the check could not run: search is down/, response.body)
  end

  test "a purge from Slack and a member purge here are both listed" do
    Fd::ChannelPurge.create!(channel_id: @id, member_id: "USUB", wanted: 30, state: "asked",
      source: "slack", asked_by: "UME")
    get fd_channel_path(@id, tab: "purge")

    assert_match(/from Slack/, response.body)
    assert_match(/Last 30/, response.body)
    assert_match(%r{/fd/members/USUB}, response.body)
  end

  test "messages that could not be deleted are shown apart, with why" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                            "user" => "USUB", "text" => "taken" }])
    Fd::PurgeItem.create!(purge_id: one.id, channel_id: @id, ts: "1700000000.000200",
      author_id: "USUB", text: "still up", state: "failed", error: "cant_delete_message",
      done_at: Time.current)
    get fd_channel_purge_path(@id, one)

    assert_select "h2.card-title", text: "Could not be deleted"
    assert_match(/still up/, response.body)
    assert_match(/cant_delete_message/, response.body)
  end

  test "thread replies start folded" do
    one = finished_purge([
      { "ts" => "1700000000.000200", "thread_ts" => "1700000000.000100",
        "user" => "UOTH", "text" => "the reply" },
      { "ts" => "1700000000.000100", "thread_ts" => nil, "user" => "USUB", "text" => "the top" }
    ])
    get fd_channel_purge_path(@id, one)

    assert_select "details.purge-thread"
    assert_select "details.purge-thread[open]", count: 0
  end

  test "a purge still waiting for its Slack confirm is not listed" do
    Fd::ChannelPurge.create!(channel_id: @id, wanted: 50, state: "proposed", source: "slack",
      asked_by: "UME")
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_no_match(/not confirmed/, response.body)
  end

  test "a failure shows why" do
    post_purge
    purges.sole.update!(state: "failed", finished_at: Time.current,
      error: "the admin account is not in the channel")
    get fd_channel_path(@id, tab: "purge")

    assert_match(/failed/, response.body)
    assert_match(/admin account is not in/, response.body)
  end

  test "a firefighter cannot purge" do
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    post_purge

    assert_equal 0, purges.count
  end

  test "a firefighter may purge one member here but not the last messages" do
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    post_member_purge
    post_purge

    assert_equal ["USUB0001"], purges.map(&:member_id)
  end

  test "a firefighter is offered only the one member purge" do
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_select %(input[name="kind"][type="hidden"][value="member"])
    assert_select "input.purge-kind-last", count: 0
    assert_no_match(/Channel messages/, response.body)
  end

  test "a community manager picks between the two" do
    get fd_channel_path(@id, tab: "purge")

    assert_select "input.purge-kind-last[checked]"
    assert_select "input.purge-kind-member"
  end

  test "somebody holding neither purge sees the button dead, with the reason" do
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    move_capability!("firefighter", "member.purge", false)
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_select %(span.btn-off[aria-disabled="true"])
    assert_no_match(/modal-open="purge-channel"/, response.body)
  end

  def finished_purge(transcript, **over)
    post_purge
    one = purges.sole
    one.update!({ state: "done", finished_at: Time.current, purged: transcript.size }.merge(over))
    kept!(one, transcript)
    one
  end

  test "a purge opens its own page" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                       "user" => "USUB", "text" => "the raid" }])
    get fd_channel_purge_path(@id, one)

    assert_response :success
    assert_match(/the raid/, response.body)
    assert_match(/Purged/, response.body)
    assert_no_match(/purgeds/, response.body)
  end

  test "the page counts as the channels section" do
    one = finished_purge([])
    get fd_channel_purge_path(@id, one)

    assert_select %(a[aria-current="page"]), text: /Channels/
  end

  test "the row links to it" do
    one = finished_purge([])
    get fd_channel_path(@id, tab: "purge")

    assert_match(%r{href="#{fd_channel_purge_path(@id, one)}"}, response.body)
  end

  test "replies sit under the message they answered" do
    one = finished_purge([
      { "ts" => "1700000000.000200", "thread_ts" => "1700000000.000100",
        "user" => "UOTH", "text" => "the reply" },
      { "ts" => "1700000000.000100", "thread_ts" => nil,
        "user" => "USUB", "text" => "the top" }
    ])
    get fd_channel_purge_path(@id, one)
    body = response.body

    assert_operator body.index("the top"), :<, body.index("the reply")
    assert_select %(details.purge-thread > summary), text: /1 reply/
  end

  test "a reply whose parent was not purged is still shown" do
    one = finished_purge([
      { "ts" => "1700000000.000200", "thread_ts" => "1700000000.000999",
        "user" => "UOTH", "text" => "an orphan" }
    ])
    get fd_channel_purge_path(@id, one)

    assert_match(/an orphan/, response.body)
  end

  test "a message with no text still shows who said it" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                       "user" => "USUB", "text" => nil }])
    get fd_channel_purge_path(@id, one)

    assert_match(/no text held/, response.body)
  end

  test "a firefighter may read one" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                       "user" => "USUB", "text" => "the raid" }])
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    get fd_channel_purge_path(@id, one)

    assert_response :success
    assert_match(/the raid/, response.body)
  end

  test "somebody without channel.guard may not" do
    one = finished_purge([])
    drop_roles!("UME")
    hold_role!("UME", "gardener")
    get fd_channel_purge_path(@id, one)

    assert_response :redirect
  end

  test "a purge from another channel is not found here" do
    one = finished_purge([])
    other = Analytics::DimChannel.where(archived: false).order(:channel_id).second
    skip "the corpus has one channel" if other.nil?

    get fd_channel_purge_path(other.channel_id, one)

    assert_response :not_found
  end
end

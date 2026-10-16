require "test_helper"

class FdChannelPurgeTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
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

  def create_deleted_items!(purge, entries)
    entries.each do |entry|
      Fd::PurgeItem.create!(purge_id: purge.id, channel_id: purge.channel_id, ts: entry["ts"],
        thread_ts: entry["thread_ts"], author_id: entry["user"], text: entry["text"],
        state: "deleted", done_at: Time.current)
    end
  end

  test "channel show purge tab returns success and renders Purge" do
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_match(/Purge/, response.body)
  end

  test "channel purges create queues a purge and writes a queued audit entry" do
    post_purge
    one = purges.sole

    assert_equal 10, one.wanted
    assert_equal "a raid", one.reason
    assert_equal "asked", one.state
    assert_equal "UME", one.asked_by
    assert_equal 1, Fd::AuditEntry.where(entity_type: "channel_purge", verb: "queued").count
  end

  test "channel purges create above MAX_MESSAGES creates no purge and alerts" do
    post_purge(wanted: (Fd::ChannelPurge::MAX_MESSAGES + 1).to_s)

    assert_equal 0, purges.count
    assert_match(/Enter 1 to 10,000/, flash[:alert])
  end

  test "channel purges create with wanted 0 creates no purge and alerts" do
    post_purge(wanted: "0")

    assert_equal 0, purges.count
    assert_match(/Enter 1 to 10,000/, flash[:alert])
  end

  test "channel purges create with blank reason creates no purge and alerts" do
    post_purge(reason: "  ")

    assert_equal 0, purges.count
    assert_match(/Enter a reason/, flash[:alert])
  end

  test "channel purges create twice creates one purge and alerts already running" do
    post_purge
    post_purge

    assert_equal 1, purges.count
    assert_match(/already running/, flash[:alert])
  end

  test "channel purges create after the first is done creates a second purge" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current)
    post_purge

    assert_equal 2, purges.count
  end

  test "purge tab renders reason and done state and purged count" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, purged: 8)
    create_deleted_items!(purges.sole, [{ "ts" => "1", "user" => "USUB", "text" => "the raid" }])
    get fd_channel_path(@id, tab: "purge")

    assert_match(/a raid/, response.body)
    assert_match(/done/, response.body)
    assert_match(/8 purged/, response.body)
  end

  test "purge reply_count counts thread replies and the tab renders them" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, purged: 4)
    create_deleted_items!(purges.sole, [
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

  test "channel purges create for a member without a count queues every message" do
    post_member_purge
    one = purges.sole

    assert_equal [@id, "USUB0001", nil], [one.channel_id, one.member_id, one.wanted]
    assert_match(/Purging every message from .+ in this channel/, flash[:notice])
    assert_equal 1, Fd::AuditEntry.where(entity_type: "member_purge", verb: "queued").count
  end

  test "channel purges create for a member with member_wanted 30 sets wanted 30" do
    post_member_purge(member_wanted: "30")
    one = purges.sole

    assert_equal ["USUB0001", 30], [one.member_id, one.wanted]
    assert_match(/Purging the last 30 messages from .+ in this channel/, flash[:notice])
  end

  test "channel purges create for a member with member_wanted 0 creates no purge" do
    post_member_purge(member_wanted: "0")

    assert_equal 0, purges.count
    assert_match(/Enter 1 to 10,000/, flash[:alert])
  end

  test "purge tab renders the Purge submit and All placeholder and no take down text" do
    get fd_channel_path(@id, tab: "purge")

    assert_match(/Purge messages in/, response.body)
    assert_select %(input[type="submit"][value="Purge"])
    assert_select %(input[name="member_wanted"][placeholder="All"])
    assert_no_match(/[Tt]ake (them )?down/, response.body)
  end

  test "channel purges create for a member without member_id creates no purge" do
    post_member_purge(member_id: "")

    assert_equal 0, purges.count
    assert_match(/Select a member/, flash[:alert])
  end

  test "channel purges create with every param and blank wanted creates no purge" do
    post_purge(wanted: "", every: "1")

    assert_equal 0, purges.count
    assert_match(/Enter 1 to 10,000/, flash[:alert])
  end

  test "channel purges create allows a member purge and a channel purge together" do
    post_purge
    post_member_purge

    assert_equal 2, purges.count
  end

  test "channel purges create twice for one member creates one purge" do
    post_member_purge
    post_member_purge

    assert_equal 1, purges.count
    assert_match(/already running/, flash[:alert])
  end

  test "channel purges create with wanted 2500 stores 2500 and flashes the count" do
    post_purge(wanted: "2500")

    assert_equal 2500, purges.sole.wanted
    assert_equal "Purging the last 2,500 messages in this channel", flash[:notice]
  end

  test "purge tab renders progress of a running member purge" do
    post_member_purge
    purges.sole.update!(state: "running", started_at: Time.current, found: 1204, purged: 120)
    get fd_channel_path(@id, tab: "purge")

    assert_match(/All messages/, response.body)
    assert_match(/120 of 1,204 purged/, response.body)
  end

  test "purge tab renders left_after_check of a done purge" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, purged: 10,
      left_after_check: 0, checked_at: Time.current)
    get fd_channel_path(@id, tab: "purge")

    assert_match(/Last 10/, response.body)
    assert_match(/0 left after the check/, response.body)
  end

  test "purge tab renders the error of a purge whose check failed" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, purged: 10,
      error: "the check could not run: search is down")
    get fd_channel_path(@id, tab: "purge")

    assert_match(/the check could not run: search is down/, response.body)
  end

  test "purge tab lists a slack member purge with source and member link" do
    Fd::ChannelPurge.create!(channel_id: @id, member_id: "USUB", wanted: 30, state: "asked",
      source: "slack", asked_by: "UME")
    get fd_channel_path(@id, tab: "purge")

    assert_match(/from Slack/, response.body)
    assert_match(/Last 30/, response.body)
    assert_match(%r{/fd/members/USUB}, response.body)
  end

  test "purge show renders failed items under a Failed card with the error" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                            "user" => "USUB", "text" => "taken" }])
    Fd::PurgeItem.create!(purge_id: one.id, channel_id: @id, ts: "1700000000.000200",
      author_id: "USUB", text: "still up", state: "failed", error: "cant_delete_message",
      done_at: Time.current)
    get fd_channel_purge_path(@id, one)

    assert_select "h2.card-title", text: "Failed"
    assert_match(/still up/, response.body)
    assert_match(/cant_delete_message/, response.body)
  end

  test "purge show renders thread replies in closed details" do
    one = finished_purge([
      { "ts" => "1700000000.000200", "thread_ts" => "1700000000.000100",
        "user" => "UOTH", "text" => "the reply" },
      { "ts" => "1700000000.000100", "thread_ts" => nil, "user" => "USUB", "text" => "the top" }
    ])
    get fd_channel_purge_path(@id, one)

    assert_select "details.purge-thread"
    assert_select "details.purge-thread[open]", count: 0
  end

  test "purge tab omits a proposed purge" do
    Fd::ChannelPurge.create!(channel_id: @id, wanted: 50, state: "proposed", source: "slack",
      asked_by: "UME")
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_no_match(/not confirmed/, response.body)
  end

  test "purge tab renders failed state and the error" do
    post_purge
    purges.sole.update!(state: "failed", finished_at: Time.current,
      error: "the admin account is not in the channel")
    get fd_channel_path(@id, tab: "purge")

    assert_match(/failed/, response.body)
    assert_match(/admin account is not in/, response.body)
  end

  test "channel purges create as firefighter creates no purge" do
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    post_purge

    assert_equal 0, purges.count
  end

  test "channel purges create as firefighter allows member purge and rejects channel purge" do
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    post_member_purge
    post_purge

    assert_equal ["USUB0001"], purges.map(&:member_id)
  end

  test "purge tab as firefighter renders only the member kind" do
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_select %(input[name="kind"][type="hidden"][value="member"])
    assert_select "input.purge-kind-last", count: 0
    assert_no_match(/Message count/, response.body)
  end

  test "purge tab as community manager renders both kinds" do
    get fd_channel_path(@id, tab: "purge")

    assert_select "input.purge-kind-last[checked]"
    assert_select "input.purge-kind-member"
  end

  test "purge tab for firefighter with member.purge off renders a disabled button and no modal" do
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    override_capability!("firefighter", "member.purge", false)
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_select %(span.btn-off[aria-disabled="true"])
    assert_no_match(/modal-open="purge-channel"/, response.body)
  end

  def finished_purge(transcript, **over)
    post_purge
    one = purges.sole
    one.update!({ state: "done", finished_at: Time.current, purged: transcript.size }.merge(over))
    create_deleted_items!(one, transcript)
    one
  end

  test "purge show renders the purge items and Purged" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                       "user" => "USUB", "text" => "the raid" }])
    get fd_channel_purge_path(@id, one)

    assert_response :success
    assert_match(/the raid/, response.body)
    assert_match(/Purged/, response.body)
    assert_no_match(/purgeds/, response.body)
  end

  test "purge show marks the Channels nav link current" do
    one = finished_purge([])
    get fd_channel_purge_path(@id, one)

    assert_select %(a[aria-current="page"]), text: /Channels/
  end

  test "purge tab links to purge show" do
    one = finished_purge([])
    get fd_channel_path(@id, tab: "purge")

    assert_match(%r{href="#{fd_channel_purge_path(@id, one)}"}, response.body)
  end

  test "purge show renders replies after their parent with a reply count" do
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

  test "purge show renders a reply whose parent is not in the purge" do
    one = finished_purge([
      { "ts" => "1700000000.000200", "thread_ts" => "1700000000.000999",
        "user" => "UOTH", "text" => "an orphan" }
    ])
    get fd_channel_purge_path(@id, one)

    assert_match(/an orphan/, response.body)
  end

  test "purge show renders No text for an item without text" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                       "user" => "USUB", "text" => nil }])
    get fd_channel_purge_path(@id, one)

    assert_match(/No text/, response.body)
  end

  test "purge show as firefighter returns success" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                       "user" => "USUB", "text" => "the raid" }])
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")
    get fd_channel_purge_path(@id, one)

    assert_response :success
    assert_match(/the raid/, response.body)
  end

  test "purge show as gardener redirects" do
    one = finished_purge([])
    revoke_roles!("UME")
    grant_role!("UME", "gardener")
    get fd_channel_purge_path(@id, one)

    assert_response :redirect
  end

  test "purge show for another channel returns 404" do
    one = finished_purge([])
    other = Analytics::DimChannel.where(archived: false).order(:channel_id).second
    skip "the corpus has one channel" if other.nil?

    get fd_channel_purge_path(other.channel_id, one)

    assert_response :not_found
  end
end

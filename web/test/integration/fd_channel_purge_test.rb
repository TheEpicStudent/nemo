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

  test "the tab shows what was taken down" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, taken_down: 8,
      transcript: [{ "ts" => "1", "user" => "USUB", "text" => "the raid" }])
    get fd_channel_path(@id, tab: "purge")

    assert_match(/a raid/, response.body)
    assert_match(/done/, response.body)
    assert_match(/8 taken down/, response.body)
  end

  test "replies taken with a thread are counted apart" do
    post_purge
    purges.sole.update!(state: "done", finished_at: Time.current, taken_down: 4,
      transcript: [
        { "ts" => "1.1", "thread_ts" => "1", "user" => "USUB", "text" => "in it" },
        { "ts" => "1.2", "thread_ts" => "1", "user" => "USUB", "text" => "again" },
        { "ts" => "1", "thread_ts" => nil, "user" => "USUB", "text" => "the top" }
      ])
    get fd_channel_path(@id, tab: "purge")

    assert_equal 2, purges.sole.reply_count
    assert_match(/2 in threads/, response.body)
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

  test "a firefighter sees the button dead, with the reason" do
    drop_roles!("UME")
    hold_role!("UME", "firefighter")
    get fd_channel_path(@id, tab: "purge")

    assert_response :success
    assert_select %(span.btn-off[aria-disabled="true"])
    assert_no_match(/modal-open="purge-channel"/, response.body)
  end

  def finished_purge(transcript, **over)
    post_purge
    one = purges.sole
    one.update!({ state: "done", finished_at: Time.current, taken_down: transcript.size,
                  transcript: transcript }.merge(over))
    one
  end

  test "a purge opens its own page" do
    one = finished_purge([{ "ts" => "1700000000.000100", "thread_ts" => nil,
                       "user" => "USUB", "text" => "the raid" }])
    get fd_channel_purge_path(@id, one)

    assert_response :success
    assert_match(/the raid/, response.body)
    assert_match(/Purged/, response.body)
    assert_no_match(/taken downs/, response.body)
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

  test "a reply whose parent was not taken is still shown" do
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

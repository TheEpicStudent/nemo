require "test_helper"

class FdChannelJoinTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    @channel = Analytics::DimChannel.where(archived: false).where("channel_id LIKE 'C%'")
      .order(:channel_id).first
    skip "the corpus has no public channel" if @channel.nil?
    @id = @channel.channel_id
    seat_nemo!(false)
  end

  def connection = ActiveRecord::Base.connection

  def seat_nemo!(inside)
    connection.execute(
      "INSERT INTO fd.channel_membership (channel_id, inside) " \
      "VALUES (#{connection.quote(@id)}, #{inside}) " \
      "ON CONFLICT (channel_id) DO UPDATE SET inside = EXCLUDED.inside"
    )
  end

  def record_join!(verb, why = nil)
    connection.execute(
      "INSERT INTO fd.channel_joins (channel_id, verb, why) " \
      "VALUES (#{connection.quote(@id)}, #{connection.quote(verb)}, #{connection.quote(why)})"
    )
  end

  def nemo_answers(state, error = nil)
    test = self
    lambda do |join_request, **|
      join_request.update!(state: state, error: error, finished_at: Time.current) unless
        state == Fd::ChannelJoinRequest::QUEUED
      test.seat_nemo!(true) if state == Fd::ChannelJoinRequest::JOINED
      join_request.reload
    end
  end

  def join_with(state, error = nil)
    original_wait = Fd::ChannelJoinRequest.method(:wait_for)
    Fd::ChannelJoinRequest.define_singleton_method(:wait_for, &nemo_answers(state, error))
    post fd_channel_join_path(@id), params: { tab: "readonly" }
  ensure
    Fd::ChannelJoinRequest.define_singleton_method(:wait_for, original_wait)
  end

  test "a public channel nemo is not in offers to join" do
    get fd_channel_path(@id)

    assert_select "p.sev-crit", "Nemo is not in the channel"
    assert_select "form[action=?] button", fd_channel_join_path(@id), text: "Join channel"
  end

  test "a channel nemo is in shows neither the warning nor the button" do
    seat_nemo!(true)

    get fd_channel_path(@id)

    assert_select "p.sev-crit", count: 0
    assert_select "form[action=?]", fd_channel_join_path(@id), count: 0
  end

  test "a private channel that needs an invite offers no join button" do
    record_join!("refused", FdChannelsHelper::NEEDS_INVITE)

    get fd_channel_path(@id)

    assert_select "p.sev-crit", FdChannelsHelper::INVITE_NOTE
    assert_select "form[action=?]", fd_channel_join_path(@id), count: 0
  end

  test "joining queues a request and the warning goes once nemo is in" do
    join_with(Fd::ChannelJoinRequest::JOINED)

    assert_redirected_to fd_channel_path(@id, tab: "readonly")
    assert_equal "Nemo joined the channel", flash[:notice]
    join_request = Fd::ChannelJoinRequest.sole
    assert_equal ["UME", @id], [join_request.requested_by, join_request.channel_id]
    assert Fd::AuditEntry.exists?(entity_type: "channel_join_request", verb: "queued")

    follow_redirect!
    assert_select "p.sev-crit", count: 0
    assert_select "form[action=?]", fd_channel_join_path(@id), count: 0
  end

  test "a refused join shows nemo's reason" do
    join_with(Fd::ChannelJoinRequest::REFUSED, "is_archived")

    assert_equal "Nemo could not join: is_archived", flash[:alert]
  end

  test "a join refused for a private channel asks for an invite" do
    join_with(Fd::ChannelJoinRequest::REFUSED, FdChannelsHelper::NEEDS_INVITE)

    assert_equal FdChannelsHelper::INVITE_NOTE, flash[:alert]
  end

  test "a join nemo has not answered yet says so" do
    join_with(Fd::ChannelJoinRequest::QUEUED)

    assert_equal "Nemo has not joined yet, reload in a moment", flash[:notice]
  end

  test "a second click while a request waits reuses it" do
    join_with(Fd::ChannelJoinRequest::QUEUED)
    join_with(Fd::ChannelJoinRequest::QUEUED)

    assert_equal 1, Fd::ChannelJoinRequest.queued.where(channel_id: @id).count
  end

  test "a legacy private channel id is refused before asking nemo" do
    post fd_channel_join_path("G01PRIVATE")

    assert_equal "Nemo can only join a public channel by itself", flash[:alert]
    assert_equal 0, Fd::ChannelJoinRequest.count
  end

  test "somebody without channel.guard cannot ask nemo to join" do
    delete logout_path
    sign_in_as(Account.create!(user_id: "UNOBODY"))

    post fd_channel_join_path(@id)

    assert_equal 0, Fd::ChannelJoinRequest.count
  end
end

require "test_helper"

class FdChannelJoinTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
    @channel = Analytics::DimChannel.where(archived: false).where("channel_id LIKE 'C%'")
      .order(:channel_id).first
    skip "the corpus has no public channel" if @channel.nil?
    @id = @channel.channel_id
    join_nemo!(false)
  end

  def connection = ActiveRecord::Base.connection

  def join_nemo!(inside)
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

  def wait_for_stub(state, error = nil)
    test = self
    lambda do |join_request, **|
      join_request.update!(state: state, error: error, finished_at: Time.current) unless
        state == Fd::ChannelJoinRequest::QUEUED
      test.join_nemo!(true) if state == Fd::ChannelJoinRequest::JOINED
      join_request.reload
    end
  end

  def join_with(state, error = nil)
    original_wait = Fd::ChannelJoinRequest.method(:wait_for)
    Fd::ChannelJoinRequest.define_singleton_method(:wait_for, &wait_for_stub(state, error))
    post fd_channel_join_path(@id), params: { tab: "readonly" }
  ensure
    Fd::ChannelJoinRequest.define_singleton_method(:wait_for, original_wait)
  end

  test "channel page with nemo not joined shows warning and join button" do
    get fd_channel_path(@id)

    assert_select "p.sev-crit", "Nemo is not a member of this channel"
    assert_select "form[action=?] button", fd_channel_join_path(@id), text: "Join channel"
  end

  test "channel page with nemo joined shows no warning and no join button" do
    join_nemo!(true)

    get fd_channel_path(@id)

    assert_select "p.sev-crit", count: 0
    assert_select "form[action=?]", fd_channel_join_path(@id), count: 0
  end

  test "channel page with needs invite refusal shows invite note and no join button" do
    record_join!("refused", FdChannelsHelper::NEEDS_INVITE)

    get fd_channel_path(@id)

    assert_select "p.sev-crit", FdChannelsHelper::INVITE_NOTE
    assert_select "form[action=?]", fd_channel_join_path(@id), count: 0
  end

  test "join creates a request and removes the warning once nemo has joined" do
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

  test "join refused by nemo sets alert with the reason" do
    join_with(Fd::ChannelJoinRequest::REFUSED, "is_archived")

    assert_equal "Join failed: is_archived", flash[:alert]
  end

  test "join refused with needs invite sets the invite note alert" do
    join_with(Fd::ChannelJoinRequest::REFUSED, FdChannelsHelper::NEEDS_INVITE)

    assert_equal FdChannelsHelper::INVITE_NOTE, flash[:alert]
  end

  test "join with a queued request sets the pending notice" do
    join_with(Fd::ChannelJoinRequest::QUEUED)

    assert_equal "Join pending", flash[:notice]
  end

  test "join twice while queued keeps one queued request" do
    join_with(Fd::ChannelJoinRequest::QUEUED)
    join_with(Fd::ChannelJoinRequest::QUEUED)

    assert_equal 1, Fd::ChannelJoinRequest.queued.where(channel_id: @id).count
  end

  test "join with a private channel id sets alert and creates no request" do
    post fd_channel_join_path("G01PRIVATE")

    assert_equal "Public channel required", flash[:alert]
    assert_equal 0, Fd::ChannelJoinRequest.count
  end

  test "join without channel.guard creates no request" do
    delete logout_path
    sign_in_as(Account.create!(user_id: "UNOBODY"))

    post fd_channel_join_path(@id)

    assert_equal 0, Fd::ChannelJoinRequest.count
  end
end

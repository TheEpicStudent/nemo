require "test_helper"

class PrometheanChannelsTest < ActionDispatch::IntegrationTest
  WHO = "UPROMCH01".freeze
  UNMEASURED_CHANNEL = "CGHOSTNOTHERE".freeze

  setup do
    @staff = Account.find_or_create_by!(user_id: WHO)
    @channel = Analytics::DimChannel.where(archived: false).first
    Prometheus::Appointment.delete_all
    Current.forget_roles
  end

  teardown do
    Prometheus::Appointment.delete_all
    Current.forget_roles
  end

  def create_appointment(channel_id, role = "manager")
    Prometheus::Appointment.insert_all!([
      { user_id: WHO, channel_id: channel_id, role: role, seen_at: Time.current }
    ])
    Current.forget_roles
  end

  test "a manager appointment carries the role and the channel" do
    skip "no measured channel in the warehouse" if @channel.nil?
    create_appointment(@channel.channel_id)

    assert_equal ["promethean"], Authz.effective_roles(WHO)
    assert Channels::Audience.may_see?(@staff, @channel.channel_id)
  end

  test "a moderator appointment carries nothing" do
    skip "no measured channel in the warehouse" if @channel.nil?
    create_appointment(@channel.channel_id, "moderator")

    assert_empty Authz.effective_roles(WHO)
    assert_not Channels::Audience.may_see?(@staff, @channel.channel_id)
  end

  test "a channel the warehouse has never seen is listed as unmeasured" do
    create_appointment(UNMEASURED_CHANNEL)

    assert_equal [UNMEASURED_CHANNEL], Channels::Audience.unmeasured_for(@staff)
    assert Channels::Audience.may_see?(@staff, UNMEASURED_CHANNEL)
  end

  test "the unmeasured channel page explains itself rather than refusing" do
    create_appointment(UNMEASURED_CHANNEL)
    sign_in_as(@staff)

    get channel_path(UNMEASURED_CHANNEL)

    assert_response :success
    assert_match(/Analytics isn't available for this channel yet/, response.body)
    assert_match UNMEASURED_CHANNEL, response.body
  end

  test "a channel they hold nothing on is still refused" do
    create_appointment(UNMEASURED_CHANNEL)
    sign_in_as(@staff)

    get channel_path("CSOMEONEELSE")

    assert_redirected_to channels_path(q: "CSOMEONEELSE")
  end

  test "the index carries the unmeasured channel" do
    create_appointment(UNMEASURED_CHANNEL)
    sign_in_as(@staff)

    get channels_path

    assert_response :success
    assert_match UNMEASURED_CHANNEL, response.body
    assert_match(/no data for this channel yet/, response.body)
  end

  test "the promethean role cannot be delegated by hand" do
    assert_not_includes Authz.grantable_roles, "promethean"
    assert_raises(Authz::Grant::NotAllowedError) do
      Authz::Grant.grant!(WHO, kind: "role", name: "promethean", by: "test")
    end
  end
end

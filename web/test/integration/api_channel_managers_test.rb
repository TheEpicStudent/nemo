require "test_helper"

class ApiChannelManagersTest < ActionDispatch::IntegrationTest
  MANAGER = "U0BGRUHPTTR".freeze
  NON_MANAGER = "U04KX9TQ2AA".freeze

  setup do
    Fd::Flag.set!(:public_api, true, by: "UBOSS")
    @client = make_app!("UOWNER1")
    @token, @secret = Api::Token.mint!(@client, "Toolbox")
    @channel = Analytics::DimChannel.first.channel_id
    Api::ChannelManager.delete_all
    Api::ChannelSweep.delete_all
    Api::RequestLog.delete_all
    Api::Consent.delete_all
    create_channel_manager(MANAGER)
  end

  teardown do
    Fd::Flag.delete_all
    Current.forget_flags
  end

  def create_channel_manager(user_id, on: @channel)
    Api::ChannelManager.create!(channel_id: on, user_id: user_id, assigned_at: 1.year.ago)
    Api::ChannelSweep.stamp!(on, 1)
  end

  def opted_in(user_id)
    Api::Consent.set!(user_id, @client.id, "channel_manager", true, via: "dashboard")
  end

  def head(key = @secret)
    { "Authorization" => "Bearer #{key}" }
  end

  def get_channel_manager(user_id, on: @channel)
    get api_v1_channel_manager_path(channel_id: on, user_id: user_id), headers: head
  end

  def body = JSON.parse(response.body)

  def body_of
    yield
    body
  end

  test "show for opted in manager returns granted with freshness and no assignment date" do
    opted_in(MANAGER)
    get_channel_manager(MANAGER)

    assert_response :success
    assert_equal [@channel, MANAGER, "granted", true], body.values_at("channel_id", "user_id",
      "consent", "is_manager")
    assert_not body["stale"]
    assert body["synced_at"].present?
    assert_not body.key?("since"), "since key is present"
  end

  test "show for opted in non manager returns is_manager false" do
    opted_in(NON_MANAGER)
    get_channel_manager(NON_MANAGER)

    assert_response :success
    assert_equal ["granted", false], body.values_at("consent", "is_manager")
  end

  test "show without consent returns withheld with opt_in_url and no is_manager" do
    get_channel_manager(MANAGER)

    assert_response :success
    assert_equal "withheld", body["consent"]
    assert_nil body["is_manager"]
    assert_match(%r{/settings/permissions\z}, body["opt_in_url"])
  end

  test "show withheld response has the same shape for manager and non manager" do
    get_channel_manager(MANAGER)
    manager_body = body

    get_channel_manager(NON_MANAGER)

    assert_equal manager_body.except("user_id"), body.except("user_id"),
      "response shape differs between manager and non manager"
  end

  test "show withheld response omits synced_at and stale" do
    get_channel_manager(MANAGER)

    assert_not body.key?("synced_at")
    assert_not body.key?("stale")
  end

  test "show for private channel returns granted and is_manager true when opted in" do
    opted_in(MANAGER)
    create_channel_manager(MANAGER, on: "C0PRIVATE99")
    get_channel_manager(MANAGER, on: "C0PRIVATE99")

    assert_response :success
    assert_equal ["granted", true], body.values_at("consent", "is_manager")
  end

  test "show for unknown channel returns granted and is_manager false" do
    opted_in(MANAGER)
    get_channel_manager(MANAGER, on: "C0NOTHINGHERE")

    assert_response :success
    assert_equal ["granted", false], body.values_at("consent", "is_manager")
  end

  test "show withheld response matches for known and unknown channel except channel_id" do
    known_body = body_of { get_channel_manager(MANAGER, on: @channel) }
    unknown_body = body_of { get_channel_manager(MANAGER, on: "C0NOSUCHTHING") }

    assert_equal "withheld", known_body["consent"]
    assert_equal known_body.except("channel_id"), unknown_body.except("channel_id"),
      "a private or unknown channel must look the same while consent is withheld"
  end

  test "show with malformed ids returns 422 and writes no request log" do
    get_channel_manager("nope")
    assert_response :unprocessable_content
    assert_equal "bad_user_id", body["error"]

    get_channel_manager(MANAGER, on: "nope")
    assert_response :unprocessable_content
    assert_equal "bad_channel_id", body["error"]
    assert_empty Api::RequestLog.all, "request log written for malformed id"
  end

  test "show writes a request log per request with subject outcome and channel" do
    opted_in(MANAGER)
    get_channel_manager(MANAGER)
    get_channel_manager(NON_MANAGER)

    request_logs = Api::RequestLog.order(:id).pluck(:subject_user_id, :outcome, :channel_id)
    assert_equal [[MANAGER, "manager", @channel], [NON_MANAGER, "withheld", @channel]], request_logs
    assert_equal [@token.id], Api::RequestLog.distinct.pluck(:token_id)
  end

  test "show withheld request does not call refresh_if_stale" do
    freshened_ids = []
    original_refresh_if_stale = ChannelManagers.method(:refresh_if_stale)
    ChannelManagers.define_singleton_method(:refresh_if_stale) { |id| freshened_ids << id }
    get_channel_manager(MANAGER)

    assert_empty freshened_ids, "refresh_if_stale called for withheld request"
    assert_equal 1, Api::RequestLog.where(outcome: "withheld").count
  ensure
    ChannelManagers.define_singleton_method(:refresh_if_stale, original_refresh_if_stale)
  end

  test "show without token returns 401 and writes no request log" do
    get api_v1_channel_manager_path(channel_id: @channel, user_id: MANAGER)

    assert_response :unauthorized
    assert_empty Api::RequestLog.all
  end
end

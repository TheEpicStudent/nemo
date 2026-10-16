require "test_helper"

class ApiAuthTest < ActionDispatch::IntegrationTest
  setup do
    Fd::Flag.set!(:public_api, true, by: "UBOSS")
    @client = make_app!("UOWNER1")
    @token, @secret = Api::Token.mint!(@client, "Toolbox")
  end

  teardown do
    Fd::Flag.delete_all
    Current.forget_flags
  end

  def get_with_key(key = @secret, path: api_v1_token_path)
    get path, headers: key ? { "Authorization" => "Bearer #{key}" } : {}
  end

  def body
    JSON.parse(response.body)
  end

  test "token show returns key metadata without the secret" do
    get_with_key

    assert_response :success
    assert_equal ["Toolbox", "UOWNER1", 20], body.values_at("name", "owner_user_id",
      "rate_per_minute")
    assert_equal @token.prefix, body["prefix"]
    assert_no_match(/#{@secret}/, response.body, "response body contains the secret")
  end

  test "missing Authorization header returns 401 invalid_token" do
    get_with_key(nil)

    assert_response :unauthorized
    assert_equal "invalid_token", body["error"]
  end

  test "unknown key returns 401 invalid_token" do
    get_with_key("nemo_live_neverissuedatall12")

    assert_response :unauthorized
    assert_equal "invalid_token", body["error"]
  end

  test "non-bearer Authorization scheme returns 401 invalid_token" do
    get api_v1_token_path, headers: { "Authorization" => "Basic #{@secret}" }

    assert_response :unauthorized
    assert_equal "invalid_token", body["error"]
  end

  test "revoked key returns 401 revoked_token" do
    @token.revoke!(by: "UOWNER1")
    get_with_key

    assert_response :unauthorized
    assert_equal "revoked_token", body["error"]
  end

  test "public_api flag off returns 503 api_off with a valid key" do
    Fd::Flag.set!(:public_api, false, by: "UBOSS")
    get_with_key

    assert_response :service_unavailable
    assert_equal "api_off", body["error"]
  end

  test "valid key sets last_used_at once within the resolution window" do
    assert_nil @token.last_used_at

    get_with_key
    first = @token.reload.last_used_at
    assert_not_nil first

    get_with_key
    assert_equal first, @token.reload.last_used_at, "last_used_at changed on the second request"
  end

  test "browser session without key returns 401 invalid_token" do
    staff = grant_role!("UBOSS2", "community_manager")
    sign_in_as(staff)

    get api_v1_token_path

    assert_response :unauthorized
    assert_equal "invalid_token", body["error"]
  end

  test "refusal responds with json media type and a message" do
    Fd::Flag.set!(:public_api, false, by: "UBOSS")
    get_with_key(nil)

    assert_equal "application/json", response.media_type
    assert body.key?("message"), "error body has no message key"
  end
end

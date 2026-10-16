require "test_helper"

class ApiRateLimitTest < ActionDispatch::IntegrationTest
  setup do
    Fd::Flag.set!(:public_api, true, by: "UBOSS")
    @client = make_app!("UOWNER1")
    @token, @secret = Api::Token.mint!(@client, "Toolbox")
  end

  teardown do
    Fd::Flag.delete_all
    Current.forget_flags
  end

  def get_token(key = @secret)
    get api_v1_token_path, headers: { "Authorization" => "Bearer #{key}" }
  end

  def rate_limit_headers
    response.headers.slice("RateLimit-Limit", "RateLimit-Remaining", "RateLimit-Reset")
  end

  def body = JSON.parse(response.body)

  test "rate_per_minute setting and token rate default to 20" do
    assert_equal 20, Api::Setting.value("rate_per_minute")
    assert_equal 20, @token.rate
  end

  test "token route sets RateLimit limit remaining and reset headers" do
    with_memory_store do
      get_token

      assert_response :success
      assert_equal "20", rate_limit_headers["RateLimit-Limit"]
      assert_equal "19", rate_limit_headers["RateLimit-Remaining"]
      assert rate_limit_headers["RateLimit-Reset"].to_i.between?(1, 60)
    end
  end

  test "RateLimit-Remaining decrements per request and floors at 0" do
    with_memory_store do
      3.times { get_token }
      assert_equal "17", rate_limit_headers["RateLimit-Remaining"]

      20.times { get_token }
      assert_equal "0", rate_limit_headers["RateLimit-Remaining"], "remaining does not go below 0"
    end
  end

  test "request over limit returns 429 rate_limited with Retry-After" do
    with_memory_store do
      20.times { get_token }
      assert_response :success

      get_token

      assert_response :too_many_requests
      assert_equal "rate_limited", body["error"]
      assert body["retry_after"].to_i.between?(1, 60)
      assert_equal response.headers["Retry-After"], body["retry_after"].to_s
    end
  end

  test "exhausted token does not reduce another token remaining" do
    with_memory_store do
      other_app = make_app!("UOWNER2", name: "Arcade")
      other_token, other_secret = Api::Token.mint!(other_app, "Arcade")
      21.times { get_token }
      assert_response :too_many_requests

      get_token(other_secret)

      assert_response :success
      assert_equal "19", rate_limit_headers["RateLimit-Remaining"]
      assert_equal other_token.rate, rate_limit_headers["RateLimit-Limit"].to_i
    end
  end

  test "token rate_limit overrides default and returns 429 after 2 requests" do
    with_memory_store do
      @token.update!(rate_limit: 2)

      2.times { get_token }
      assert_response :success
      assert_equal "2", rate_limit_headers["RateLimit-Limit"]

      get_token
      assert_response :too_many_requests
    end
  end

  test "unknown token returns 401 with no RateLimit headers" do
    with_memory_store do
      get_token("nemo_live_neverissuedatall12")

      assert_response :unauthorized
      assert_empty rate_limit_headers, "RateLimit headers absent"
    end
  end

  test "channel manager check decrements RateLimit-Remaining" do
    with_memory_store do
      channel = Analytics::DimChannel.first.channel_id
      get api_v1_channel_manager_path(channel_id: channel, user_id: "U0BGRUHPTTR"),
        headers: { "Authorization" => "Bearer #{@secret}" }

      assert_response :success
      assert_equal "19", rate_limit_headers["RateLimit-Remaining"]
    end
  end
end

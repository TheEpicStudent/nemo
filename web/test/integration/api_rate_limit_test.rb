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

  test "the default budget is twenty a minute" do
    assert_equal 20, Api::Setting.value("rate_per_minute")
    assert_equal 20, @token.rate
  end

  test "every answer says how much budget is left" do
    with_a_real_cache do
      get_token

      assert_response :success
      assert_equal "20", rate_limit_headers["RateLimit-Limit"]
      assert_equal "19", rate_limit_headers["RateLimit-Remaining"]
      assert rate_limit_headers["RateLimit-Reset"].to_i.between?(1, 60)
    end
  end

  test "the remaining budget counts down, and stops at nought" do
    with_a_real_cache do
      3.times { get_token }
      assert_equal "17", rate_limit_headers["RateLimit-Remaining"]

      20.times { get_token }
      assert_equal "0", rate_limit_headers["RateLimit-Remaining"], "it never goes negative"
    end
  end

  test "past the budget it refuses, and says when to come back" do
    with_a_real_cache do
      20.times { get_token }
      assert_response :success

      get_token

      assert_response :too_many_requests
      assert_equal "rate_limited", body["error"]
      assert body["retry_after"].to_i.between?(1, 60)
      assert_equal response.headers["Retry-After"], body["retry_after"].to_s
    end
  end

  test "one token running hot does not spend another token's budget" do
    with_a_real_cache do
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

  test "a token with its own limit is held to that, not the shared one" do
    with_a_real_cache do
      @token.update!(rate_limit: 2)

      2.times { get_token }
      assert_response :success
      assert_equal "2", rate_limit_headers["RateLimit-Limit"]

      get_token
      assert_response :too_many_requests
    end
  end

  test "a refusal before the token is known carries no budget at all" do
    with_a_real_cache do
      get_token("nemo_live_neverissuedatall12")

      assert_response :unauthorized
      assert_empty rate_limit_headers, "there is no budget to report without a token"
    end
  end

  test "the budget is spent on checks too, not only on the token route" do
    with_a_real_cache do
      channel = Analytics::DimChannel.first.channel_id
      get api_v1_channel_manager_path(channel_id: channel, user_id: "U0BGRUHPTTR"),
        headers: { "Authorization" => "Bearer #{@secret}" }

      assert_response :success
      assert_equal "19", rate_limit_headers["RateLimit-Remaining"]
    end
  end
end

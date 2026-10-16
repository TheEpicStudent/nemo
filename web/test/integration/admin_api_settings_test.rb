require "test_helper"

class AdminApiSettingsTest < ActionDispatch::IntegrationTest
  setup do
    @manager = grant_role!("UBOSS9", "community_manager")
    grant_role!("UFIRE9", "firefighter")
    @client = make_app!("UOWNER9")
    @token, = Api::Token.mint!(@client, "Toolbox")
    sign_in_as(@manager)
  end

  def setting_values
    Api::Setting::DEFAULTS.keys.index_with { |key| Api::Setting.value(key) }
  end

  test "admin api page lists token name with key prefix and rate setting" do
    get admin_api_path

    assert_response :success
    assert_select ".data-table td", text: "Toolbox"
    assert_select ".data-table .tag", text: @token.display_prefix
    assert_select ".setlist .setname", text: "Requests per minute per key"
  end

  test "setting update by manager changes value and creates one event" do
    assert_difference -> { Api::Event.count }, 1 do
      patch admin_api_setting_path, params: { key: "rate_per_minute", value: 250 }
    end

    assert_equal 250, Api::Setting.value("rate_per_minute")
    event = Api::Event.last
    assert_equal ["setting_changed", @manager.user_id, "20 to 250"],
      [event.verb, event.actor_user_id, event.detail]
  end

  test "setting update with unknown key or invalid value changes nothing" do
    original_values = setting_values

    patch admin_api_setting_path, params: { key: "wingspan", value: 5 }
    assert_match(/not a setting/, flash[:alert])

    patch admin_api_setting_path, params: { key: "rate_per_minute", value: 0 }
    assert_match(/greater than zero/, flash[:alert])

    patch admin_api_setting_path, params: { key: "rate_per_minute", value: 999_999_999 }
    assert_match(/exceeds the maximum/, flash[:alert])

    assert_equal original_values, setting_values
    assert_equal 0, Api::Event.count
  end

  test "token rate update sets rate limit and blank value clears it" do
    patch admin_api_token_rate_path(@token), params: { value: 600 }
    assert_equal 600, @token.reload.rate

    patch admin_api_token_rate_path(@token), params: { value: "" }
    assert_nil @token.reload.rate_limit
    assert_equal Api::Setting.value("rate_per_minute"), @token.rate
    assert_equal 2, Api::Event.where(verb: "token_rate_set").count
  end

  test "token destroy by manager revokes token and logs owner in event detail" do
    delete admin_api_token_path(@token)

    assert_predicate @token.reload, :revoked?
    assert_equal @manager.user_id, @token.revoked_by
    event = Api::Event.where(verb: "token_revoked").sole
    assert_match(/owned by UOWNER9/, event.detail)
  end

  test "token destroy on revoked token flashes alert and creates no event" do
    delete admin_api_token_path(@token)

    assert_no_difference -> { Api::Event.count } do
      delete admin_api_token_path(@token)
    end

    assert_match(/Live key not found/, flash[:alert])
  end

  test "firefighter setting update and token destroy change nothing" do
    sign_in_as(Account.find("UFIRE9"))

    patch admin_api_setting_path, params: { key: "rate_per_minute", value: 999 }
    delete admin_api_token_path(@token)

    assert_equal 20, Api::Setting.value("rate_per_minute")
    assert_not_predicate @token.reload, :revoked?
    assert_equal 0, Api::Event.count
  end

  test "admin api page for firefighter redirects to root" do
    sign_in_as(Account.find("UFIRE9"))
    get admin_api_path

    assert_redirected_to root_path
  end
end

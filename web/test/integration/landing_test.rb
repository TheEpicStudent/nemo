require "test_helper"

class LandingTest < ActionDispatch::IntegrationTest
  setup do
    @member = Account.create!(user_id: "ULANDING1")
  end

  teardown do
    OmniAuth.config.test_mode = false
    OmniAuth.config.mock_auth[:hackclub] = nil
  end

  test "signed out root renders the landing page with the Hack Club Auth form" do
    get root_path

    assert_response :success
    assert_select "body.landing"
    assert_select "h1", text: "Community analytics and conduct casework for Hack Club."
    assert_select "form[action=?][method=post]", "/auth/hackclub", minimum: 2
    assert_select "button[type=submit]", text: /Sign in with Hack Club Auth/
  end

  test "signed out root renders without the app shell" do
    get root_path

    assert_select ".sidebar", count: 0
    assert_select "script[type=importmap]", count: 1
  end

  test "signed in root keeps the app home" do
    sign_in_as(@member)
    get root_path

    assert_response :success
    assert_select "body.landing", count: 0
  end

  test "login redirects to the landing page" do
    get login_path

    assert_redirected_to root_path
  end

  test "a signed out deep link returns there after sign in" do
    get channels_path
    assert_redirected_to root_path

    sign_in_as(@member)

    assert_redirected_to channels_path
  end

  test "sign in without a stored path lands on root" do
    sign_in_as(@member)

    assert_redirected_to root_path
  end

  test "return path accepts local paths only" do
    assert_match SessionsController::RETURN_PATH, "/channels?range=30"
    assert_no_match SessionsController::RETURN_PATH, "//evil.example"
    assert_no_match SessionsController::RETURN_PATH, "/\\evil.example"
    assert_no_match SessionsController::RETURN_PATH, "https://evil.example"
  end

  test "signed out json requests get 401 and store no return path" do
    get channels_path(format: :json)

    assert_response :unauthorized
    assert_nil session[:return_to]
  end

  test "auth failure renders on the landing layout" do
    get auth_failure_path(message: "no_slack_id")

    assert_response :success
    assert_select "body.landing"
    assert_select "h1", text: "Sign-in failed"
    assert_select "form[action=?]", "/auth/hackclub"
  end

  test "logout redirects to the landing page" do
    sign_in_as(@member)
    delete logout_path

    assert_redirected_to root_path
    assert_nil session[:user_id]
  end
end

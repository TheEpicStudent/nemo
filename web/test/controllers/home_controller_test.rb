require "test_helper"

class HomeControllerTest < ActionDispatch::IntegrationTest
  teardown do
    OmniAuth.config.test_mode = false
    OmniAuth.config.mock_auth[:hackclub] = nil
  end

  test "community manager sees the home dashboard" do
    staff = hold_role!("UTESTCM1", "community_manager")
    sign_in_as(staff)

    get root_path

    assert_response :success
  end

  test "the clock follows the timezone the browser wrote" do
    staff = hold_role!("UTESTTZ1", "community_manager")
    sign_in_as(staff)

    cookies[:mn_tz] = "Asia/Kolkata"
    get root_path

    assert_response :success
    assert_equal "Asia/Kolkata", @controller.send(:viewer_zone)
  end

  test "a timezone nobody has heard of falls back to UTC" do
    staff = hold_role!("UTESTTZ2", "community_manager")
    sign_in_as(staff)

    cookies[:mn_tz] = "Moon/Sea_of_Tranquility"
    get root_path

    assert_response :success
    assert_equal "UTC", @controller.send(:viewer_zone)
  end

  test "unauthenticated visitor is redirected to login" do
    get root_path

    assert_redirected_to login_path
  end

  test "a staff row with no roles reaches the front door, not the dashboard" do
    staff = Account.create!(user_id: "UTESTNONE1")
    sign_in_as(staff)

    get root_path

    assert_response :success
  end
end

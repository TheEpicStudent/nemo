require "test_helper"

class AnalyticsFlagTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
    Fd::Flag.delete_all
    Current.forget_flags
  end

  teardown do
    Fd::Flag.delete_all
    Current.forget_flags
  end

  def disable_analytics
    Fd::Flag.set!(:analytics, false, by: @me.user_id)
  end

  test "analytics pages with analytics flag off redirect to fd cases with alert" do
    disable_analytics

    [community_path, channels_path, engine_path].each do |where|
      get where
      assert_redirected_to fd_cases_path
      assert_match(/Community analytics turned off/, flash[:alert])
    end
  end

  test "engine sync with analytics flag off redirects to fd cases" do
    disable_analytics

    post engine_sync_path
    assert_redirected_to fd_cases_path
  end

  test "channels and community pages with analytics flag default render" do
    get channels_path
    assert_response :success

    get community_path
    assert_response :success
  end

  test "fd case show with analytics flag off renders" do
    disable_analytics
    kase = make_case
    Fd::CaseThread.create!(case_id: kase.id, channel_id: "C0LOUNGE", thread_ts: "1.1",
      is_primary: true, added_by: @me.user_id)

    get fd_case_path(kase)
    assert_response :success
  end
end

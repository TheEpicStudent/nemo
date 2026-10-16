require "test_helper"

class JourneyRoutesTest < ActionDispatch::IntegrationTest
  setup do
    @manager = grant_role!("UJRBOSS", "community_manager")
    sign_in_as(@manager)
  end

  test "journey stage paths return success" do
    ApplicationHelper::JOURNEY.each do |_label, stage|
      get public_send(:"#{stage}_journey_path")
      assert_response :success, "#{stage} did not render"
    end
  end

  test "legacy journey paths redirect with 301 to /journey" do
    ApplicationHelper::LEGACY_JOURNEY_PATHS.each do |old_path, new_path|
      get "/#{old_path}"
      assert_redirected_to "/journey/#{new_path}"
      assert_response :moved_permanently, "/#{old_path} must not become a soft redirect"
    end
  end

  test "ACTIONS maps replies to replies and excludes answered" do
    assert_equal "replies", ApplicationHelper::ACTIONS.fetch("replies"),
      "replies maps to replies"
    assert_not_includes ApplicationHelper::ACTIONS.values, "answered"
  end
end

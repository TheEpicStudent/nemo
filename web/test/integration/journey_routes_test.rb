require "test_helper"

class JourneyRoutesTest < ActionDispatch::IntegrationTest
  setup do
    @manager = hold_role!("UJRBOSS", "community_manager")
    sign_in_as(@manager)
  end

  test "every stage answers under /journey" do
    ApplicationHelper::JOURNEY.each do |_label, stage|
      get public_send(:"#{stage}_journey_path")
      assert_response :success, "#{stage} did not render"
    end
  end

  test "the old top level paths still land, permanently" do
    ApplicationHelper::LEGACY_JOURNEY_PATHS.each do |old_path, new_path|
      get "/#{old_path}"
      assert_redirected_to "/journey/#{new_path}"
      assert_response :moved_permanently, "/#{old_path} must not become a soft redirect"
    end
  end

  test "the stage a route names is the action it reaches" do
    assert_equal "replies", ApplicationHelper::ACTIONS.fetch("replies"),
      "route, action and label all say replies now"
    assert_not_includes ApplicationHelper::ACTIONS.values, "answered"
  end
end

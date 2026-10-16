require "test_helper"

class ChannelsRangeTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  test "index with the default range returns success" do
    get channels_path
    assert_response :success
  end

  test "index with each preset range and a condition and sort returns success" do
    Channels::Window::PRESETS.each do |days|
      get channels_path(days: days, sort: "messages", direction: "desc",
        match: "all", c: { "0" => { "f" => "messages", "op" => "gt", "v" => ["1"] } })
      assert_response :success, "days=#{days} must render"
    end
  end

  test "index with an unlisted days value uses a preset or the loaded days" do
    get channels_path(days: "45; drop table raw.message")
    assert_response :success
    assert_includes Channels::Window::PRESETS + [@controller.view_assigns["window"].loaded_days],
      @controller.view_assigns["window"].days
  end
end

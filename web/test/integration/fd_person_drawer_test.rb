require "test_helper"

class FdPersonDrawerTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def get_drawer(user_id)
    get fd_member_path(user_id), headers: { "Turbo-Frame" => "person-drawer" }
  end

  test "member with Turbo-Frame header returns success and the person-drawer frame" do
    get_drawer "UNOBODY"

    assert_response :success
    assert_match "person-drawer", response.body
  end

  test "drawer request does not create an AccessLog row" do
    assert_no_difference -> { AccessLog.count } do
      get_drawer "USUB"
    end
  end

  test "drawer without case.read does not return 200" do
    sign_in_as(Account.create!(user_id: "UPLAIN"))

    get_drawer "USUB"

    refute_equal 200, response.status
  end

  test "drawer request runs no roster query" do
    queries = []
    subscriber = ->(*, payload) { queries << payload[:sql] if payload[:sql].to_s.include?("FROM roster") }

    ActiveSupport::Notifications.subscribed(subscriber, "sql.active_record") { get_drawer "USUB" }

    assert_response :success
    assert_empty queries, "no roster query for the drawer"
  end

  test "member page runs a roster query" do
    queries = []
    subscriber = ->(*, payload) { queries << payload[:sql] if payload[:sql].to_s.include?("FROM roster") }

    ActiveSupport::Notifications.subscribed(subscriber, "sql.active_record") { get fd_member_path("USUB") }

    assert_response :success
    assert_not_empty queries, "roster query expected on the member page"
  end
end

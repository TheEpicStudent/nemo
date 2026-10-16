require "test_helper"

class Fd::MembersControllerTest < ActionDispatch::IntegrationTest
  teardown do
    OmniAuth.config.test_mode = false
    OmniAuth.config.mock_auth[:hackclub] = nil
  end

  def member_with_unique_handle
    handle = Fd::Member.live.where.not(handle: [nil, ""]).where("length(handle) >= 4")
      .group(:handle).having("count(*) = 1").order(Arel.sql("min(user_id)")).limit(1).pluck(:handle).first
    handle && Fd::Member.live.find_by(handle: handle)
  end

  test "pane with q renders matching member row fragment without layout" do
    sign_in_as(grant_role!("UTESTCM1", "community_manager"))
    member = member_with_unique_handle
    skip "the corpus has no member with a handle of its own" if member.nil?

    get fd_member_pane_path(q: member.handle), headers: { "Accept" => "text/html" }

    assert_response :success
    assert_includes response.body, member.user_id
    assert_includes response.body, "pane-filter-target=\"row\""
    assert_not_includes response.body, "<html"
  end

  test "pane without q renders default roster rows" do
    sign_in_as(grant_role!("UTESTCM1", "community_manager"))

    get fd_member_pane_path, headers: { "Accept" => "text/html" }

    assert_response :success
    assert_includes response.body, "pane-filter-target=\"row\""
  end
end

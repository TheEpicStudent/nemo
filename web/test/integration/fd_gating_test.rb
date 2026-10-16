require "test_helper"

class FdGatingTest < ActionDispatch::IntegrationTest
  setup do
    @me = Account.create!(user_id: "UFF1")
    grant_role!("UFF1", "firefighter")
    sign_in_as(@me)
  end

  def grant_role(role)
    grant_role!("UFF1", role)
  end

  test "case show assigned to another user returns success" do
    kase = make_case(assign: "UOTHER")

    get fd_case_path(kase)

    assert_response :success

    get fd_case_path(kase, tab: "people")
  end

  test "resolution create on a case assigned to another user resolves it" do
    kase = make_case(assign: "UOTHER")

    get fd_case_path(kase)

    post fd_case_resolution_path(kase), params: { outcome: "close", close_reason: "no_action" }
    assert kase.reload.resolved?
  end

  test "resolution destroy on a case assigned to another user reopens it" do
    kase = make_case(assign: "UOTHER", resolved_at: 1.day.ago, resolution: "no_action")

    get fd_case_path(kase)

    delete fd_case_resolution_path(kase)
    assert_not kase.reload.resolved?
  end

  test "resolution with report outcome and no case.act creates no action" do
    kase = make_case(assign: "UFF1")
    override_capability!("firefighter", "case.act", false, by: "UME")

    post fd_case_resolution_path(kase), params: { outcome: "report", type_key: "temp_ban",
      target_user_id: "USUB" }

    assert_equal 0, Fd::Action.where(case_id: kase.id).count
    assert_not kase.reload.resolved?

    post fd_case_resolution_path(kase), params: { outcome: "close", close_reason: "no_action" }
    assert kase.reload.resolved?, "close outcome resolves without case.act"
  end

  test "palette row Log an action has why without case.act and other rows have none" do
    kase = make_case(assign: "UOTHER")
    override_capability!("firefighter", "case.act", false, by: "UME")

    get fd_search_path(format: :json, q: ">", on_case: kase.id)

    rows = response.parsed_body["groups"].first["rows"]
    act = rows.find { |row| row["title"] == "Log an action" }
    assert_equal "log an action against a member is Firefighter only", act["why"]
    assert_nil rows.find { |row| row["title"] == "Resolve this case" }["why"]
    assert_nil rows.find { |row| row["title"] == "Go to cases" }["why"]
  end
end

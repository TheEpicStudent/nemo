require "test_helper"

class FdQueueTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    @own_case = make_case
    @other_case = make_case
    @unassigned_case = make_case
    sign_in_as(@me)
  end

  def query(**filters)
    Fd::CaseQuery.new(filters.transform_keys(&:to_s), viewer: "UME")
  end

  def listed?(kase, **filters)
    query(**filters).relation.exists?(id: kase.id)
  end

  test "CaseQuery view mine lists only cases assigned to the viewer" do
    @own_case.assign!("UME")
    @other_case.assign!("UOTHER")

    assert listed?(@own_case, view: "mine")
    assert_not listed?(@other_case, view: "mine"), "case assigned to another user is not listed"
    assert_not listed?(@unassigned_case, view: "mine"), "unassigned case is not listed"
  end

  test "CaseQuery view mine lists a case assigned to the viewer and another user" do
    @own_case.assign!("UOTHER")
    @own_case.assign!("UME")

    assert listed?(@own_case, view: "mine")
  end

  test "CaseQuery view mine excludes a case after the viewer assignee is destroyed" do
    @own_case.assign!("UME")
    @own_case.assignees.sole.destroy!

    assert_not listed?(@own_case, view: "mine")
  end

  test "CaseQuery view mine excludes a resolved case" do
    @own_case.assign!("UME")
    @own_case.update!(resolved_at: 1.hour.ago, resolution: "no_action")

    assert_not listed?(@own_case, view: "mine")
  end

  test "assign! reduces the unresolved unassigned count by one" do
    before = Fd::Case.unresolved.unassigned.count
    @unassigned_case.assign!("UME")

    assert_equal before - 1, Fd::Case.unresolved.unassigned.count
  end

  test "assign! for two users reduces the unresolved unassigned count by one" do
    before = Fd::Case.unresolved.unassigned.count
    @unassigned_case.assign!("UME")
    @unassigned_case.assign!("UOTHER")

    assert_equal before - 1, Fd::Case.unresolved.unassigned.count
  end

  test "CaseQuery default lists recent assigned and unassigned cases and not resolved ones" do
    recent_unassigned = make_case(opened_at: 1.hour.ago)
    recent_assigned = make_case(opened_at: 1.hour.ago, assign: "UOTHER")
    resolved = make_case(opened_at: 1.hour.ago, resolved_at: Time.current, resolution: "no_action")

    assert listed?(recent_unassigned), "unassigned case is listed"
    assert listed?(recent_assigned), "assigned open case is listed"
    assert_not listed?(resolved), "resolved case is not listed"
  end

  test "CaseQuery view mine sets assignee me and status open" do
    query = Fd::CaseQuery.new({ "view" => "mine" }, viewer: "UME")

    assert_equal "me", query["assignee"]
    assert_equal "open", query["status"]
  end

  test "CaseQuery with facet filters has no view and filters by category" do
    @own_case.assign!("UME")
    @own_case.update!(category_key: "spam")
    @other_case.assign!("UME")

    filters = { status: "open", assignee: "me", category: "spam" }

    assert listed?(@own_case, **filters)
    assert_not listed?(@other_case, **filters), "category filter excludes the case"
    assert_nil query(**filters).view, "view is nil with facet filters"
  end

  test "CaseQuery view none has no view and lists cases" do
    assert_nil query(view: "none").view
    assert query(view: "none").relation.exists?
  end
end

require "test_helper"

class FdQueueTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
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

  test "the mine filter lists what I am on and nothing else" do
    @own_case.assign!("UME")
    @other_case.assign!("UOTHER")

    assert listed?(@own_case, view: "mine")
    assert_not listed?(@other_case, view: "mine"), "somebody else's case is not mine"
    assert_not listed?(@unassigned_case, view: "mine"), "an unassigned case is not mine either"
  end

  test "a case I share with somebody else is still mine" do
    @own_case.assign!("UOTHER")
    @own_case.assign!("UME")

    assert listed?(@own_case, view: "mine")
  end

  test "the mine filter drops a case once I step off it" do
    @own_case.assign!("UME")
    @own_case.assignees.sole.destroy!

    assert_not listed?(@own_case, view: "mine")
  end

  test "a resolved case of mine is not in the open queue" do
    @own_case.assign!("UME")
    @own_case.update!(resolved_at: 1.hour.ago, resolution: "no_action")

    assert_not listed?(@own_case, view: "mine")
  end

  test "the unassigned count falls by one when a case is taken" do
    before = Fd::Case.unresolved.unassigned.count
    @unassigned_case.assign!("UME")

    assert_equal before - 1, Fd::Case.unresolved.unassigned.count
  end

  test "a case on two people counts as assigned once, not twice" do
    before = Fd::Case.unresolved.unassigned.count
    @unassigned_case.assign!("UME")
    @unassigned_case.assign!("UOTHER")

    assert_equal before - 1, Fd::Case.unresolved.unassigned.count
  end

  test "needs attention keeps a fresh claimed case as well as a free one" do
    recent_unassigned = make_case(opened_at: 1.hour.ago)
    recent_assigned = make_case(opened_at: 1.hour.ago, assign: "UOTHER")
    resolved = make_case(opened_at: 1.hour.ago, resolved_at: Time.current, resolution: "no_action")

    assert listed?(recent_unassigned), "nobody is on it"
    assert listed?(recent_assigned), "somebody is on it, but it is still open"
    assert_not listed?(resolved), "resolved cases stay off the queue"
  end

  test "choosing a view sets the facets it implies" do
    query = Fd::CaseQuery.new({ "view" => "mine" }, viewer: "UME")

    assert_equal "me", query["assignee"]
    assert_equal "open", query["status"]
  end

  test "changing a facet turns the view off and keeps what the view had set" do
    @own_case.assign!("UME")
    @own_case.update!(category_key: "spam")
    @other_case.assign!("UME")

    filters = { status: "open", assignee: "me", category: "spam" }

    assert listed?(@own_case, **filters)
    assert_not listed?(@other_case, **filters), "the category still narrows it"
    assert_nil query(**filters).view, "no view is in force once you filter"
  end

  test "clearing the last facet of a view does not fall back into that view" do
    assert_nil query(view: "none").view
    assert query(view: "none").relation.exists?
  end
end

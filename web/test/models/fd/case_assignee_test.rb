require "test_helper"

class Fd::CaseAssigneeTest < ActiveSupport::TestCase
  setup do
    @own_case = make_case
    @other_case = make_case
    @unassigned_case = make_case
  end

  def seeded_cases
    Fd::Case.where(id: [@own_case.id, @other_case.id, @unassigned_case.id])
  end

  test "case without assignees is not assigned? and has no assignee_user_ids" do
    assert_not @unassigned_case.assigned?
    assert_empty @unassigned_case.assignee_user_ids
  end

  test "assign! stores user_id and assigned_by and assigned_at" do
    @own_case.assign!("UME")
    assignee = @own_case.assignees.sole

    assert_equal "UME", assignee.user_id
    assert_equal "UME", assignee.assigned_by
    assert_not_nil assignee.assigned_at
  end

  test "assign! with by stores the assigner as assigned_by" do
    @own_case.assign!("UTHEM", by: "UME")
    assert_equal "UME", @own_case.assignees.sole.assigned_by
  end

  test "assign! with two users stores both and assigned_to? matches only them" do
    @own_case.assign!("UONE")
    @own_case.assign!("UTWO")

    assert_equal %w[UONE UTWO], @own_case.reload.assignee_user_ids
    assert @own_case.assigned_to?("UTWO")
    assert_not @own_case.assigned_to?("USOMEBODY")
  end

  test "assign! with the same user twice raises RecordNotUnique" do
    @own_case.assign!("UONE")
    assert_raises(ActiveRecord::RecordNotUnique) { @own_case.assign!("UONE") }
  end

  test "assigned_to returns the cases assigned to the user" do
    @own_case.assign!("UME")
    @other_case.assign!("UOTHER")

    assert_equal [@own_case.id], seeded_cases.assigned_to("UME").ids
    assert_equal [@other_case.id], seeded_cases.assigned_to("UOTHER").ids
  end

  test "unassigned returns only cases without assignees" do
    @own_case.assign!("UME")
    @other_case.assign!("UOTHER")

    assert_equal [@unassigned_case.id], seeded_cases.unassigned.ids
  end

  test "destroying the last assignee makes the case unassigned" do
    @own_case.assign!("UME")
    @own_case.assignees.sole.destroy!

    assert_not @own_case.reload.assigned?
    assert_includes seeded_cases.unassigned.ids, @own_case.id
  end

  test "assignee_user_ids orders by assigned_at ascending" do
    @own_case.assignees.create!(user_id: "ULATE", assigned_by: "ULATE", assigned_at: 1.hour.ago)
    @own_case.assignees.create!(user_id: "UEARLY", assigned_by: "UEARLY", assigned_at: 3.hours.ago)

    assert_equal %w[UEARLY ULATE], @own_case.reload.assignee_user_ids
  end
end

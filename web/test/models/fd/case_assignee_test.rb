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

  test "a case nobody has taken reads as unassigned" do
    assert_not @unassigned_case.assigned?
    assert_empty @unassigned_case.assignee_user_ids
  end

  test "assigning records who did it, not only who it went to" do
    @own_case.assign!("UME")
    person = @own_case.assignees.sole

    assert_equal "UME", person.user_id
    assert_equal "UME", person.assigned_by
    assert_not_nil person.assigned_at
  end

  test "one firefighter can put a case on another" do
    @own_case.assign!("UTHEM", by: "UME")
    assert_equal "UME", @own_case.assignees.sole.assigned_by
  end

  test "a case can be on several people at once" do
    @own_case.assign!("UONE")
    @own_case.assign!("UTWO")

    assert_equal %w[UONE UTWO], @own_case.reload.assignee_user_ids
    assert @own_case.assigned_to?("UTWO")
    assert_not @own_case.assigned_to?("USOMEBODY")
  end

  test "the same person twice is refused by the key, not silently doubled" do
    @own_case.assign!("UONE")
    assert_raises(ActiveRecord::RecordNotUnique) { @own_case.assign!("UONE") }
  end

  test "assigned_to finds every case somebody is on" do
    @own_case.assign!("UME")
    @other_case.assign!("UOTHER")

    assert_equal [@own_case.id], seeded_cases.assigned_to("UME").ids
    assert_equal [@other_case.id], seeded_cases.assigned_to("UOTHER").ids
  end

  test "unassigned excludes cases that are on somebody, and keeps the rest" do
    @own_case.assign!("UME")
    @other_case.assign!("UOTHER")

    assert_equal [@unassigned_case.id], seeded_cases.unassigned.ids
  end

  test "taking somebody off puts the case back in the queue" do
    @own_case.assign!("UME")
    @own_case.assignees.sole.destroy!

    assert_not @own_case.reload.assigned?
    assert_includes seeded_cases.unassigned.ids, @own_case.id
  end

  test "assignees come back oldest first, so the first to take it reads first" do
    @own_case.assignees.create!(user_id: "ULATE", assigned_by: "ULATE", assigned_at: 1.hour.ago)
    @own_case.assignees.create!(user_id: "UEARLY", assigned_by: "UEARLY", assigned_at: 3.hours.ago)

    assert_equal %w[UEARLY ULATE], @own_case.reload.assignee_user_ids
  end
end

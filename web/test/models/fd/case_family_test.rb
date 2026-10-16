require "test_helper"

class Fd::CaseFamilyTest < ActiveSupport::TestCase
  def mark_duplicate(kase, into:)
    kase.update!(resolved_at: Time.current, resolution: "duplicate", duplicate_of: into.id)
    kase
  end

  test "family_ids of a standalone case contains only the case" do
    kase = make_case

    assert_equal [kase.id], kase.family_ids
    assert_empty kase.merged_in
    assert_not kase.merged?
    assert_not kase.duplicate?
    assert_equal kase.id, kase.root.id
  end

  test "root family_ids and merged_in list its duplicates oldest first" do
    root = make_case(opened_at: 10.days.ago)
    first = mark_duplicate(make_case(opened_at: 8.days.ago), into: root)
    second = mark_duplicate(make_case(opened_at: 5.days.ago), into: root)

    assert_equal [root.id, first.id, second.id].sort, root.family_ids.sort
    assert_equal [first.id, second.id], root.merged_in.map(&:id)
    assert root.merged?
  end

  test "duplicate case returns the target as root and only itself in family_ids" do
    root = make_case(opened_at: 10.days.ago)
    duplicate = mark_duplicate(make_case(opened_at: 2.days.ago), into: root)

    assert duplicate.duplicate?
    assert_equal root.id, duplicate.root.id
    assert_equal [duplicate.id], duplicate.family_ids, "duplicate family_ids contains only itself"
  end

  test "root family_ids and merged_in include a duplicate of a later duplicate" do
    root = make_case(opened_at: 20.days.ago)
    middle = make_case(opened_at: 10.days.ago)
    leaf = mark_duplicate(make_case(opened_at: 5.days.ago), into: middle)
    mark_duplicate(middle, into: root)

    assert_includes root.family_ids, middle.id
    assert_includes root.family_ids, leaf.id, "leaf is included through the middle case"
    assert_equal 3, root.family_ids.size
    assert_equal [middle.id, leaf.id], root.merged_in.map(&:id)
  end

  test "family_ids has no repeated ids" do
    root = make_case(opened_at: 10.days.ago)
    mark_duplicate(make_case(opened_at: 5.days.ago), into: root)

    assert_equal root.family_ids.uniq, root.family_ids
  end

  test "family_of terminates for a duplicate_of cycle" do
    one = make_case(opened_at: 10.days.ago)
    two = make_case(opened_at: 5.days.ago)
    one.update_columns(duplicate_of: two.id)
    two.update_columns(duplicate_of: one.id)

    assert_equal 2, Fd::Case.family_of(one.id).size
    assert_includes [one.id, two.id], one.root.id
  end

  test "family_of accepts a case id" do
    root = make_case(opened_at: 10.days.ago)
    duplicate = mark_duplicate(make_case(opened_at: 2.days.ago), into: root)

    assert_equal [root.id, duplicate.id].sort, Fd::Case.family_of(root.id).sort
  end

  test "family_ids excludes duplicates of an unrelated case" do
    root = make_case(opened_at: 10.days.ago)
    other = make_case(opened_at: 9.days.ago)
    mark_duplicate(make_case(opened_at: 2.days.ago), into: other)

    assert_equal [root.id], root.family_ids
  end
end

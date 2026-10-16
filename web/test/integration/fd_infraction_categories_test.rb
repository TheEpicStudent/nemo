require "test_helper"

class FdInfractionCategoriesTest < ActionDispatch::IntegrationTest
  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def category(key) = Fd::InfractionCategory.find(key)

  def audited(key, verb)
    Fd::AuditEntry.where(entity_type: "infraction_category", entity_ref: key, verb: verb)
  end

  def categories_tab
    get fd_configuration_path(tab: "categories")
    response.body
  end

  test "the categories tab lists every category with its key and actions" do
    categories_tab

    assert_select ".data-table tbody tr", 22
    assert_select ".data-table td.mono", "impersonation"
    assert_select "[data-modal-id-value=add-category]"
    assert_select "form[action=?] button", retire_fd_infraction_category_path("spam"), text: "Retire"
  end

  test "adding a category makes its key from the label and puts it last" do
    post fd_infraction_categories_path, params: { label: "Raid coordination" }

    added = category("raid_coordination")
    assert_equal "Raid coordination", added.label
    assert_equal 23, added.position
    assert_equal "Raid coordination added", flash[:notice]
    assert audited("raid_coordination", "added").exists?
  end

  test "a label whose key is taken gets a numbered key" do
    post fd_infraction_categories_path, params: { label: "Spam" }

    assert_equal "Spam", category("spam_2").label
  end

  test "a blank label is refused" do
    post fd_infraction_categories_path, params: { label: "  " }

    assert_equal "Enter a label", flash[:alert]
    assert_equal 22, Fd::InfractionCategory.count
  end

  test "renaming changes the label and is audited" do
    patch fd_infraction_category_path("spam"), params: { label: "Spam or mass pings" }

    assert_equal "Spam or mass pings", category("spam").label
    assert_equal "Spam, mass pings or invites", audited("spam", "renamed").sole.before["label"]
  end

  test "moving swaps places with the neighbour" do
    post move_fd_infraction_category_path("adult", direction: "up")

    assert_equal [1, 2], [category("adult").position, category("nos").position]
  end

  test "the first category cannot move up" do
    post move_fd_infraction_category_path("nos", direction: "up")

    assert_equal 1, category("nos").position
  end

  test "a retired category leaves the case form but keeps its label" do
    kase = make_case(subject: "USUB")
    kase.update!(category_key: "adult")
    post retire_fd_infraction_category_path("adult")

    assert_equal "Adult retired", flash[:notice]
    assert audited("adult", "retired").exists?
    get fd_case_path(kase)
    assert_select "select[name=category_key] option[value=spam]"
    assert_select "select[name=category_key] option[value=adult]", 0
    assert_match "Retired", categories_tab
    assert_equal "Adult", Fd::Case.category_label("adult")
  end

  test "a retired category can be restored" do
    category("adult").update!(retired_at: Time.current)

    post restore_fd_infraction_category_path("adult")

    assert_nil category("adult").retired_at
    assert_equal "Adult restored", flash[:notice]
  end

  test "somebody without app.configure cannot change categories" do
    drop_roles!("UME")
    hold_role!("UME", "gardener")

    post retire_fd_infraction_category_path("adult")

    assert_nil category("adult").retired_at
  end
end

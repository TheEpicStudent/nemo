require "test_helper"

class FdInfractionCategoriesTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
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

  test "configuration categories tab lists 22 categories with key and Retire action" do
    categories_tab

    assert_select ".data-table tbody tr", 22
    assert_select ".data-table td.mono", "impersonation"
    assert_select "[data-modal-id-value=add-category]"
    assert_select "form[action=?] button", retire_fd_infraction_category_path("spam"), text: "Retire"
  end

  test "infraction categories create derives the key from the label and appends position 23" do
    post fd_infraction_categories_path, params: { label: "Raid coordination" }

    added = category("raid_coordination")
    assert_equal "Raid coordination", added.label
    assert_equal 23, added.position
    assert_equal "Raid coordination added", flash[:notice]
    assert audited("raid_coordination", "added").exists?
  end

  test "infraction categories create with a taken key appends a numeric suffix" do
    post fd_infraction_categories_path, params: { label: "Spam" }

    assert_equal "Spam", category("spam_2").label
  end

  test "infraction categories create with blank label alerts and adds no row" do
    post fd_infraction_categories_path, params: { label: "  " }

    assert_equal "Enter a label", flash[:alert]
    assert_equal 22, Fd::InfractionCategory.count
  end

  test "infraction categories update changes the label and writes a renamed audit entry" do
    patch fd_infraction_category_path("spam"), params: { label: "Spam or mass pings" }

    assert_equal "Spam or mass pings", category("spam").label
    assert_equal "Spam, mass pings or invites", audited("spam", "renamed").sole.before["label"]
  end

  test "infraction categories move up swaps position with the previous category" do
    post move_fd_infraction_category_path("adult", direction: "up")

    assert_equal [1, 2], [category("adult").position, category("nos").position]
  end

  test "infraction categories move up on the first category keeps position 1" do
    post move_fd_infraction_category_path("nos", direction: "up")

    assert_equal 1, category("nos").position
  end

  test "infraction categories retire removes the case form option and keeps the label" do
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

  test "infraction categories restore clears retired_at" do
    category("adult").update!(retired_at: Time.current)

    post restore_fd_infraction_category_path("adult")

    assert_nil category("adult").retired_at
    assert_equal "Adult restored", flash[:notice]
  end

  test "infraction categories retire as gardener keeps retired_at nil" do
    revoke_roles!("UME")
    grant_role!("UME", "gardener")

    post retire_fd_infraction_category_path("adult")

    assert_nil category("adult").retired_at
  end

  def log_action(kase, category_key, reversed: false)
    Fd::Action.create!(case_id: kase.id, type_key: "warning", target_user_id: "USUB", decided_by: "UFF1",
      performed_by: "UFF1", source_app: "fire_engine", category_key: category_key,
      reversed_at: (Time.current if reversed), reversed_by: ("UFF1" if reversed))
  end

  test "categories tab counts cases the way the case list filters them" do
    case_only = make_case(category_key: "nos")
    action_only = make_case(category_key: nil)
    log_action(action_only, "nos")
    overridden = make_case(category_key: "nos")
    log_action(overridden, "spam")
    reversed_action = make_case(category_key: "nos")
    log_action(reversed_action, "spam", reversed: true)

    counts = Fd::CaseQuery.category_counts
    listed = Fd::CaseQuery.new({ "category" => "nos" }).relation.pluck(:id)

    assert_equal [case_only.id, action_only.id, reversed_action.id].sort, listed.sort
    assert_equal listed.size, counts["nos"]
    assert_equal 1, counts["spam"]
    nos_count_text = Nokogiri::HTML(categories_tab).at_css("a[href='#{fd_cases_path(category: "nos")}']").text
    assert_equal "3", nos_count_text
  end
end

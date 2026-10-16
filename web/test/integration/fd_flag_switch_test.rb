require "test_helper"

class FdFlagSwitchTest < ActionDispatch::IntegrationTest
  setup do
    @manager = grant_role!("UBOSS", "community_manager")
    Fd::Flag.delete_all
    Current.forget_flags
  end

  teardown do
    Fd::Flag.delete_all
    Current.forget_flags
  end

  test "admin flags page returns success" do
    sign_in_as(@manager)
    get admin_flags_path

    assert_response :success
  end

  def flag_on(key)
    Fd::Flag.find_by(key: key.to_s)&.is_on
  end

  test "flag update by manager sets is_on false then true with notices" do
    sign_in_as(@manager)

    patch fd_flag_path, params: { key: "fire_engine", on: "0" }
    assert_redirected_to admin_flags_path
    assert_match(/Fire engine turned off/, flash[:notice])
    assert_equal false, flag_on(:fire_engine)

    patch fd_flag_path, params: { key: "fire_engine", on: "1" }
    assert_match(/Fire engine turned on/, flash[:notice])
    assert_equal true, flag_on(:fire_engine)
    assert_equal 1, Fd::Flag.where(key: "fire_engine").count, "one flag row"
  end

  test "flag update as firefighter writes no flag and flashes alert" do
    firefighter = Account.create!(user_id: "UHAND")
    grant_role!("UHAND", "firefighter")
    sign_in_as(firefighter)

    patch fd_flag_path, params: { key: "analytics", on: "0" }

    assert_nil flag_on(:analytics), "no flag row written"
    assert_not_nil flash[:alert]
  end

  test "flag update creates turned_off audit entry with actor and flag" do
    sign_in_as(@manager)

    patch fd_flag_path, params: { key: "analytics", on: "0" }

    entry = Fd::AuditEntry.where(verb: "turned_off").last
    assert_equal "UBOSS", entry.actor_user_id
    assert_equal "analytics", entry.after["flag"]
  end

  test "flag update with unknown key redirects with not a flag alert" do
    sign_in_as(@manager)

    patch fd_flag_path, params: { key: "teleporter", on: "0" }

    assert_redirected_to admin_flags_path
    assert_match(/not a flag/, flash[:alert])
  end
end

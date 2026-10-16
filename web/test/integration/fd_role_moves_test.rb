require "test_helper"

class FdRoleMovesTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def move(role, key, allowed)
    patch fd_role_permission_path, params: { role: role, key: key, allowed: allowed }
  end

  test "admin roles as firefighter redirects to root" do
    get admin_roles_path

    revoke_roles!("UME")
    grant_role!("UME", "firefighter")

    get admin_roles_path
    assert_redirected_to root_path, "the admin section is managers only"
  end

  test "move to 0 redirects to admin roles and stores an override with allowed false" do
    move("firefighter", "slack.link", "0")

    assert_redirected_to admin_roles_path
    follow_redirect!
    refute Authz::Override.find_by(role: "firefighter", capability: "slack.link").allowed
  end

  test "move to 0 then 1 sets the override allowed to false then true" do
    move("firefighter", "slack.link", "0")
    assert_equal false, Authz::Override.find_by(role: "firefighter", capability: "slack.link").allowed

    move("firefighter", "slack.link", "1")
    assert_equal true, Authz::Override.find_by(role: "firefighter", capability: "slack.link").allowed
  end

  test "move writes a revoked audit entry for the role and capability" do
    move("firefighter", "slack.link", "0")

    entry = Fd::AuditEntry.where(entity_type: "permission").recent_first.first
    assert_equal ["revoked", "UME"], [entry.verb, entry.actor_user_id]
    assert_equal "firefighter/slack.link", entry.entity_ref
    assert_equal({ "permission" => "slack.link", "role" => "firefighter",
                   "allowed" => false }, entry.after)
  end

  test "move access.grant alerts that it is locked" do
    get admin_roles_path

    move("firefighter", "access.grant", "1")
    assert_equal "access.grant is locked", flash[:alert]
  end

  test "move case.read and identity.read alerts that each is locked" do
    get admin_roles_path

    move("firefighter", "case.read", "0")
    assert_equal "case.read is locked", flash[:alert]

    move("firefighter", "identity.read", "0")
    assert_equal "identity.read is locked", flash[:alert]
  end

  test "move revokes slack.link from firefighter and the manager keeps it" do
    move("firefighter", "slack.link", "0")

    assert_nil flash[:alert]
    refute Authz.holds?(grant_role!("UFFONLY", "firefighter"), "slack.link")
    assert Authz.holds?(@me, "slack.link"), "a manager holds everything"
  end

  test "move on community_manager alerts that it has every capability" do
    move("community_manager", "slack.link", "0")

    assert_equal "community_manager has every capability", flash[:alert]
  end

  test "move as firefighter stores no override and writes a refused audit entry" do
    revoke_roles!("UME")
    grant_role!("UME", "firefighter")

    move("firefighter", "case.reverse", "0")

    assert_empty Authz::Override.all
    assert_equal 1, Fd::AuditEntry.where(verb: "refused", actor_user_id: "UME").count
  end
end

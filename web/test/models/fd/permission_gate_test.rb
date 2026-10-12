require "test_helper"

module Fd
  class PermissionGateTest < ActiveSupport::TestCase
    STAFF_ID = "UME".freeze
    OTHER_STAFF_ID = "UTHEM".freeze

    CHECKS = YAML.load_file(Rails.root.join("../db/permission_checks.yml"))
      .fetch("checks").freeze

    setup do
      @by = hold_role!("UBOSS", "community_manager")
    end

    def staff_with_role(role, manager: false)
      if manager
        staff = Account.find_or_create_by!(user_id: STAFF_ID)
        hold_role!(staff.user_id, "community_manager")
        return staff.tap { Current.forget_roles }
      end
      return Account.new(user_id: STAFF_ID) if role.nil?

      hold_role!(STAFF_ID, role).tap { Current.forget_roles }
    end

    def case_for(kind)
      case kind
      when "free" then make_case
      when "mine" then make_case(assign: STAFF_ID)
      when "theirs" then make_case(assign: OTHER_STAFF_ID)
      end
    end

    def move_capabilities(key, overrides)
      overrides.to_h.each { |role, allowed| move_capability!(role, key, allowed, by: @by.user_id) }
    end

    test "every check in the shared file agrees" do
      failures = CHECKS.filter_map do |check|
        Authz::Override.delete_all
        drop_roles!(STAFF_ID)
        Current.forget_roles

        staff = staff_with_role(check["role"], manager: check["manager"] == true)
        move_capabilities(check["key"], check["moved"])
        record = case_for(check["case"])

        result = Access.allow?(staff, check["key"], record)
        next if result == check["allowed"]

        "#{check['name']}: got #{result}, wanted #{check['allowed']}"
      end

      assert_empty failures, failures.join("\n")
    end

    test "the file covers every scoped permission, so a new scope cannot slip in unchecked" do
      scoped = Authz.keys.select { |key| Authz.record_scope(key) == :assigned }
      checked = CHECKS.filter_map { |check| check["key"] if check["case"] == "theirs" }.uniq

      assert_equal [], scoped - checked,
        "add a check for these to db/permission_checks.yml"
    end

    test "a refusal says why, in words the bot can say too" do
      staff = staff_with_role("firefighter")

      assert_equal "grant and revoke access is Community manager only",
        Access.why_not(staff, "access.grant")
    end
  end
end

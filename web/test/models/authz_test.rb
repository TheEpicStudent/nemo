require "test_helper"

class AuthzTest < ActiveSupport::TestCase
  def rows(sql)
    ApplicationRecord.connection.select_all(sql).to_a
  end

  test "Authz.keys match app.capability rows" do
    in_yaml = Authz.keys.sort
    in_table = rows("SELECT key FROM app.capability").map { |row| row["key"] }.sort

    assert_equal in_yaml, in_table,
      "db/capabilities.yml and app.capability disagree, run `nemo provision`"
  end

  test "Authz.baseline matches app.role_capability for every role" do
    Authz.role_names.reject { |role| Authz.superadmin?(role) }.each do |role|
      in_table = rows(ApplicationRecord.sanitize_sql([
        "SELECT capability FROM app.role_capability WHERE role = ?", role
      ])).map { |row| row["capability"] }.sort

      assert_equal Authz.baseline(role).sort, in_table, "#{role} baseline has drifted"
    end
  end

  test "Authz record_scope and flags match app.capability columns" do
    rows("SELECT key, record_scope, logged, every_account, locked FROM app.capability").each do |row|
      key = row["key"]
      expected_scope = Authz.record_scope(key)&.to_s
      if expected_scope.nil?
        assert_nil row["record_scope"], "#{key} scope"
      else
        assert_equal expected_scope, row["record_scope"], "#{key} scope"
      end
      assert_equal Authz.logged?(key), row["logged"], "#{key} logged"
      assert_equal Authz.every_account?(key), row["every_account"], "#{key} every_account"
      assert_equal Authz.locked?(key), row["locked"], "#{key} locked"
    end
  end

  test "Authz.record_scope raises UnknownError for an unknown key" do
    assert_raises(Authz::UnknownError) { Authz.record_scope("case.explode") }
  end

  test "Authz.record_scope and scoped? report the message.read author scope" do
    assert_equal :author, Authz.record_scope("message.read")
    assert Authz.scoped?("message.read")
    assert_not Authz.scoped?("case.resolve")
  end

  test "Authz.may? is true only for every-account keys without grants" do
    account_without_grants = Account.new(user_id: "UNOBODY9")

    assert Authz.may?(account_without_grants, "channel.read")
    assert_not Authz.may?(account_without_grants, "slack.link")
    assert_not Authz.may?(account_without_grants, "case.read")
    assert_not Authz.may?(account_without_grants, "access.grant")
  end

  test "Authz.may? is false for a nil account" do
    assert_not Authz.may?(nil, "channel.read")
    assert_not Authz.may?(nil, "case.read")
  end
end

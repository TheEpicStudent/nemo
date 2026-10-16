require "test_helper"

class Fd::ActionEnforcementTest < ActiveSupport::TestCase
  test "guard_kind and guard_scope map shush and channel_ban to their guard kind and scope" do
    assert_equal "shush", Fd::Action.guard_kind("shush")
    assert_equal "workspace", Fd::Action.guard_scope("shush")
    assert_equal "channel_ban", Fd::Action.guard_kind("channel_ban")
    assert_equal "channel", Fd::Action.guard_scope("channel_ban")
  end

  test "guard_kind is nil and enforceable? is false for kinds without an enforce block" do
    %w[warning locked_thread dm].each do |type_key|
      assert_nil Fd::Action.guard_kind(type_key), type_key
      assert_not Fd::Action.enforceable?(type_key), type_key
    end
  end

  test "ban kinds map to the deactivation guard kind with account scope" do
    %w[temp_ban indef_ban perma_ban].each do |type_key|
      assert_equal Fd::MemberGuard::DEACTIVATION, Fd::Action.guard_kind(type_key), type_key
      assert_equal "account", Fd::Action.guard_scope(type_key), type_key
      assert Fd::Action.enforceable?(type_key), type_key
    end
  end

  test "guard_kind is nil and enforceable? is false for an unknown kind" do
    assert_nil Fd::Action.guard_kind("nonsense")
    assert_not Fd::Action.enforceable?("nonsense")
  end

  test "ENFORCEABLE lists the declared enforce kinds" do
    assert_equal %w[shush temp_ban indef_ban perma_ban channel_ban].sort,
      Fd::Action::ENFORCEABLE.sort
  end

  test "ENFORCE rows have a known guard kind and scope and carry value" do
    Fd::Action::ENFORCE.each_value do |row|
      assert_includes Fd::MemberGuard::KINDS, row.fetch("guard")
      assert_includes %w[workspace channel account], row.fetch("scope")
      assert_includes %w[reactive applied], row.fetch("carry")
    end
  end

  test "channel scoped kinds are listed in TAKES_CHANNEL" do
    Fd::Action::ENFORCE.each do |type_key, row|
      next unless row["scope"] == "channel"

      assert_includes Fd::Action::TAKES_CHANNEL, type_key
    end
  end
end

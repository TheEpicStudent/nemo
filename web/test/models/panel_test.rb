require "test_helper"

class PanelTest < ActiveSupport::TestCase
  test "Panel.needs is nil or a key in Authz.keys for every panel" do
    Panel.keys.each do |key|
      want = Panel.needs(key)
      next if want.nil?

      assert_includes Authz.keys, want, "panel #{key} needs #{want}, which is not a capability"
    end
  end

  test "open panel is visible to a signed in account and not to nil" do
    assert Panel.visible?("overview.team_stats", Account.new(user_id: "UANY"))
    assert_not Panel.visible?("overview.team_stats", nil)
  end

  test "gated panel is not visible to an account without the capability" do
    bare = Account.new(user_id: "UBARE1")

    assert_not Panel.visible?("members.directory", bare)
  end

  test "visible? raises UnknownError for an unknown panel" do
    assert_raises(Panel::UnknownError) { Panel.visible?("overview.teleporter", nil) }
  end

  test "analytics panels are open and members.directory needs member.read" do
    assert Panel.open?("overview.team_stats")
    assert Panel.open?("journey.distribution")
    assert Panel.open?("journey.top_posters")
    assert_nil Panel.needs("journey.top_posters")
    assert_not Panel.open?("members.directory")
    assert_equal "member.read", Panel.needs("members.directory")
  end

  test "journey.top_posters is visible to a signed in account and not to nil" do
    assert Panel.visible?("journey.top_posters", Account.new(user_id: "UBARE1"))
    assert_not Panel.visible?("journey.top_posters", nil)
  end
end

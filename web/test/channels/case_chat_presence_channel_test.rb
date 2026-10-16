require "test_helper"

class CaseChatPresenceChannelTest < ActionCable::Channel::TestCase
  setup do
    @original_cache = Rails.cache
    Rails.cache = ActiveSupport::Cache::MemoryStore.new
    @kase = make_case
  end

  teardown { Rails.cache = @original_cache }

  test "subscribe as community_manager confirms and tracks presence through beat and unsubscribe" do
    grant_role!("UME", "community_manager")
    stub_connection(user_id: "UME")

    subscribe(case_id: @kase.id)

    assert subscription.confirmed?
    assert_equal %w[UME], Fd::ChatPresence.present_user_ids(@kase.id)

    travel 100.seconds do
      assert_empty Fd::ChatPresence.present_user_ids(@kase.id), "presence expires without beat"
      perform :beat
      assert_equal %w[UME], Fd::ChatPresence.present_user_ids(@kase.id), "beat restores presence"
    end

    unsubscribe
    assert_empty Fd::ChatPresence.present_user_ids(@kase.id)
  end

  test "subscribe without a role is rejected and adds no presence" do
    Account.find_or_create_by!(user_id: "UNOBODY")
    stub_connection(user_id: "UNOBODY")

    subscribe(case_id: @kase.id)

    assert subscription.rejected?
    assert_empty Fd::ChatPresence.present_user_ids(@kase.id)
  end

  test "subscribe with an unknown case id is rejected" do
    grant_role!("UME", "community_manager")
    stub_connection(user_id: "UME")

    subscribe(case_id: 0)

    assert subscription.rejected?
  end
end

require "test_helper"

class ChannelManagersTest < ActiveSupport::TestCase
  CHANNEL = "C0BGRUMA85D".freeze

  setup do
    @calls = []
    @original_role_id = ENV["SLACK_CHANNEL_MANAGER_ROLE_ID"]
    ENV["SLACK_CHANNEL_MANAGER_ROLE_ID"] = "Rl0A"
    Api::ChannelManager.delete_all
    Api::ChannelSweep.delete_all
    Rails.cache.clear
  end

  teardown do
    ENV["SLACK_CHANNEL_MANAGER_ROLE_ID"] = @original_role_id
  end

  def stub_proxy_call(handler)
    original_call = Slack::ProxyClient.method(:call)
    Slack::ProxyClient.define_singleton_method(:call, &handler)
    yield
  ensure
    Slack::ProxyClient.define_singleton_method(:call, original_call)
  end

  def page(*user_ids, on: CHANNEL, cursor: nil)
    {
      "ok" => true,
      "role_assignments" => user_ids.map do |user_id|
        { "role_id" => "Rl0A", "entity_id" => on, "user_id" => user_id,
          "date_create" => 1_700_000_000 }
      end,
      "response_metadata" => { "next_cursor" => cursor.to_s }
    }
  end

  def stub_pages(*pages, &block)
    replies = pages.dup
    calls = @calls
    fallback = page
    stub_proxy_call(lambda { |method, params, **options|
      calls << [method, params, options]
      replies.shift || fallback
    }, &block)
  end

  def stub_error(error, &block)
    calls = @calls
    stub_proxy_call(lambda { |*_args, **_options|
      calls << :tried
      raise error
    }, &block)
  end

  test "for fetches an unknown channel once and stores its managers" do
    manager_ids = stub_pages(page("U1", "U2")) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1 U2], manager_ids
    assert_equal 1, @calls.size
    assert_equal %w[U1 U2], Api::ChannelManager.user_ids_in(CHANNEL)
    assert_equal 2, Api::ChannelSweep.find(CHANNEL).managers
  end

  test "for calls admin.roles.listAssignments with one role and one channel" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }

    method, params, options = @calls.sole
    assert_equal "admin.roles.listAssignments", method
    assert_equal "Rl0A", params[:role_ids]
    assert_equal CHANNEL, params[:entity_ids]
    assert_equal "admin", options[:credential]
  end

  test "for with a fresh channel makes no slack call" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    @calls.clear

    manager_ids = stub_pages { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1], manager_ids
    assert_empty @calls, "fresh channel makes no call"
  end

  test "for with no managers stores a zero count and does not refetch" do
    stub_pages(page) { ChannelManagers.for(CHANNEL) }
    @calls.clear

    assert_empty stub_pages { ChannelManagers.for(CHANNEL) }
    assert_empty @calls, "empty result is cached"
    assert_equal 0, Api::ChannelSweep.find(CHANNEL).managers
  end

  test "for refetches when synced_at is stale" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)
    @calls.clear

    manager_ids = stub_pages(page("U2")) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U2], manager_ids
    assert_equal 1, @calls.size
  end

  test "for refresh removes managers missing from the new page" do
    stub_pages(page("U1", "U2")) { ChannelManagers.for(CHANNEL) }
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)

    stub_pages(page("U2")) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U2], Api::ChannelManager.user_ids_in(CHANNEL)
    assert_not ChannelManagers.manages?(CHANNEL, "U1")
  end

  test "for with a stale channel already claimed makes no call and returns stored managers" do
    with_memory_store do
      stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
      Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)
      @calls.clear
      ChannelManagers.claim(CHANNEL)

      manager_ids = stub_pages(page("U2")) { ChannelManagers.for(CHANNEL) }

      assert_empty @calls, "claimed channel serves the stored managers"
      assert_equal %w[U1], manager_ids
    end
  end

  test "for fetches a never-synced channel even when it is claimed" do
    with_memory_store do
      ChannelManagers.claim(CHANNEL)

      manager_ids = stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }

      assert_equal %w[U1], manager_ids,
        "never-synced channel is fetched despite the claim"
    end
  end

  test "for after a refresh serves the next caller without a call" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)
    @calls.clear

    stub_pages(page("U2")) { ChannelManagers.for(CHANNEL) }
    stub_pages(page("U3")) { ChannelManagers.for(CHANNEL) }

    assert_equal 1, @calls.size
    assert_equal %w[U2], Api::ChannelManager.user_ids_in(CHANNEL)
  end

  test "for on UnavailableError returns the stored managers" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    original_synced_at = Api::ChannelSweep.find(CHANNEL).synced_at
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)

    manager_ids = stub_error(Slack::ProxyClient::UnavailableError) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1], manager_ids
    assert_not_equal original_synced_at, Api::ChannelSweep.find(CHANNEL).synced_at
    assert_equal %w[U1], Api::ChannelManager.user_ids_in(CHANNEL)
  end

  test "for on an error response keeps the stored managers" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)

    stub_pages({ "ok" => false, "error" => "missing_scope" }) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1], Api::ChannelManager.user_ids_in(CHANNEL)
  end

  test "for ignores assignments for another channel" do
    stub_pages(page("U1", on: "COTHER")) { ChannelManagers.for(CHANNEL) }

    assert_empty Api::ChannelManager.user_ids_in(CHANNEL)
    assert_equal 0, Api::ChannelSweep.find(CHANNEL).managers
  end

  test "for follows next_cursor across pages" do
    manager_ids = stub_pages(page("U1", cursor: "expand"), page("U2")) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1 U2], manager_ids
    assert_equal 2, @calls.size
    assert_nil @calls.first[1][:cursor], "first call sends no cursor"
    assert_equal "expand", @calls.last[1][:cursor]
  end

  test "for without SLACK_CHANNEL_MANAGER_ROLE_ID makes no call and creates no sweep" do
    ENV["SLACK_CHANNEL_MANAGER_ROLE_ID"] = nil
    manager_ids = stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }

    assert_empty manager_ids
    assert_empty @calls
    assert_nil Api::ChannelSweep.find_by(channel_id: CHANNEL)
  end

  test "for with a blank channel id returns empty without a call" do
    assert_empty stub_pages { ChannelManagers.for("") }
    assert_empty @calls
  end
end

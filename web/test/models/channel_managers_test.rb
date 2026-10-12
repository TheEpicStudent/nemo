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

  test "a channel nobody has asked about is fetched once and remembered" do
    manager_ids = stub_pages(page("U1", "U2")) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1 U2], manager_ids
    assert_equal 1, @calls.size
    assert_equal %w[U1 U2], Api::ChannelManager.user_ids_in(CHANNEL)
    assert_equal 2, Api::ChannelSweep.find(CHANNEL).managers
  end

  test "it asks slack for one channel and one role, never the whole workspace" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }

    method, params, options = @calls.sole
    assert_equal "admin.roles.listAssignments", method
    assert_equal "Rl0A", params[:role_ids]
    assert_equal CHANNEL, params[:entity_ids]
    assert_equal "admin", options[:credential]
  end

  test "a fresh channel is answered without troubling slack at all" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    @calls.clear

    manager_ids = stub_pages { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1], manager_ids
    assert_empty @calls, "a warm channel must cost nothing"
  end

  test "a channel nobody manages is remembered as empty, not refetched forever" do
    stub_pages(page) { ChannelManagers.for(CHANNEL) }
    @calls.clear

    assert_empty stub_pages { ChannelManagers.for(CHANNEL) }
    assert_empty @calls, "no rows is an answer, not a cold cache"
    assert_equal 0, Api::ChannelSweep.find(CHANNEL).managers
  end

  test "once the stamp goes stale it is fetched again" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)
    @calls.clear

    manager_ids = stub_pages(page("U2")) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U2], manager_ids
    assert_equal 1, @calls.size
  end

  test "a refresh replaces the channel, so somebody who stepped down stops managing it" do
    stub_pages(page("U1", "U2")) { ChannelManagers.for(CHANNEL) }
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)

    stub_pages(page("U2")) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U2], Api::ChannelManager.user_ids_in(CHANNEL)
    assert_not ChannelManagers.manages?(CHANNEL, "U1")
  end

  test "a stale channel already being refreshed is not fetched a second time" do
    with_a_real_cache do
      stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
      Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)
      @calls.clear
      ChannelManagers.claim(CHANNEL)

      manager_ids = stub_pages(page("U2")) { ChannelManagers.for(CHANNEL) }

      assert_empty @calls, "somebody else holds the lock, so this caller serves what we have"
      assert_equal %w[U1], manager_ids
    end
  end

  test "a cold channel is always fetched, lock or no lock" do
    with_a_real_cache do
      ChannelManagers.claim(CHANNEL)

      manager_ids = stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }

      assert_equal %w[U1], manager_ids,
        "answering false about a channel we never read is worse than waiting"
    end
  end

  test "a refreshed channel is fresh again, so the next caller asks nothing" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)
    @calls.clear

    stub_pages(page("U2")) { ChannelManagers.for(CHANNEL) }
    stub_pages(page("U3")) { ChannelManagers.for(CHANNEL) }

    assert_equal 1, @calls.size
    assert_equal %w[U2], Api::ChannelManager.user_ids_in(CHANNEL)
  end

  test "slack falling over serves what we already hold and leaves the stamp alone" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    original_synced_at = Api::ChannelSweep.find(CHANNEL).synced_at
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)

    manager_ids = stub_error(Slack::ProxyClient::UnavailableError) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1], manager_ids
    assert_not_equal original_synced_at, Api::ChannelSweep.find(CHANNEL).synced_at
    assert_equal %w[U1], Api::ChannelManager.user_ids_in(CHANNEL)
  end

  test "a refusal from slack does not wipe the channel" do
    stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }
    Api::ChannelSweep.find(CHANNEL).update!(synced_at: 2.hours.ago)

    stub_pages({ "ok" => false, "error" => "missing_scope" }) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1], Api::ChannelManager.user_ids_in(CHANNEL)
  end

  test "an assignment on some other channel is dropped, whatever slack sends" do
    stub_pages(page("U1", on: "COTHER")) { ChannelManagers.for(CHANNEL) }

    assert_empty Api::ChannelManager.user_ids_in(CHANNEL)
    assert_equal 0, Api::ChannelSweep.find(CHANNEL).managers
  end

  test "it follows the cursor to the end" do
    manager_ids = stub_pages(page("U1", cursor: "expand"), page("U2")) { ChannelManagers.for(CHANNEL) }

    assert_equal %w[U1 U2], manager_ids
    assert_equal 2, @calls.size
    assert_nil @calls.first[1][:cursor], "the first call sends no cursor at all"
    assert_equal "expand", @calls.last[1][:cursor]
  end

  test "with no role id pinned it asks nothing and claims nothing" do
    ENV["SLACK_CHANNEL_MANAGER_ROLE_ID"] = nil
    manager_ids = stub_pages(page("U1")) { ChannelManagers.for(CHANNEL) }

    assert_empty manager_ids
    assert_empty @calls
    assert_nil Api::ChannelSweep.find_by(channel_id: CHANNEL)
  end

  test "a blank channel id is answered without a query" do
    assert_empty stub_pages { ChannelManagers.for("") }
    assert_empty @calls
  end
end

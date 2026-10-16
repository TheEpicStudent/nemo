require "test_helper"

class Slack::AnalyticsTest < ActiveSupport::TestCase
  test "parallel keeps results in the order the tasks were given" do
    assert_equal [:a, :b, :c], Slack::Analytics.parallel(
      -> { sleep 0.05; :a },
      -> { :b },
      -> { sleep 0.02; :c }
    )
  end

  test "parallel re-raises an exception from a task" do
    original_report_on_exception = Thread.report_on_exception
    Thread.report_on_exception = false
    err = assert_raises(RuntimeError) do
      Slack::Analytics.parallel(-> { :ok }, -> { raise "boom" })
    end
    assert_equal "boom", err.message
  ensure
    Thread.report_on_exception = original_report_on_exception
  end

  test "parallel overlaps its tasks" do
    started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    Slack::Analytics.parallel(-> { sleep 0.5 }, -> { sleep 0.5 })
    elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started

    assert_operator elapsed, :<, 0.9, "tasks ran sequentially in #{elapsed.round(2)}s"
  end

  CHANNEL_ROW = { "channel_id" => "C1", "name" => "general", "messages_count" => 12 }.freeze

  def with_memory_cache
    original_cache = Rails.cache
    Rails.cache = ActiveSupport::Cache::MemoryStore.new
    yield
  ensure
    Rails.cache = original_cache
  end

  def fetch_activity(**over)
    Slack::Analytics.channel_activity(
      **{ channel_id: "C1", name: "general", from: "2026-08-01", to: "2026-08-07" }.merge(over)
    )
  end

  RANGE = { "start_date" => "2026-01-01", "end_date" => "2026-12-31" }.freeze

  def stub_slack(reply)
    original_call = Slack::ProxyClient.method(:call)
    count = 0
    Slack::ProxyClient.define_singleton_method(:call) do |method, *args|
      next RANGE if method == "admin.analytics.getAvailableDateRange"

      count += 1
      reply.call(method, *args)
    end
    yield -> { count }
  ensure
    Slack::ProxyClient.define_singleton_method(:call, original_call)
  end

  def one_channel = ->(*) { { "channel_analytics" => [CHANNEL_ROW] } }

  test "channel_activity with the same window calls slack once" do
    with_memory_cache do
      stub_slack(one_channel) do |calls|
        first = fetch_activity
        second = fetch_activity

        assert_equal 1, calls.call, "second call is served from the cache"
        assert_equal 12, first.stats["messages_count"]
        assert_equal first.stats, second.stats
      end
    end
  end

  test "channel_activity with a different window calls slack again" do
    with_memory_cache do
      stub_slack(one_channel) do |calls|
        fetch_activity
        fetch_activity(to: "2026-08-08")

        assert_equal 2, calls.call, "a different date range is not served from the cache"
      end
    end
  end

  test "channel_activity does not cache an error" do
    with_memory_cache do
      stub_slack(->(*) { raise Slack::ProxyClient::Error, "down" }) do |calls|
        assert_equal :unavailable, fetch_activity.error
        assert_equal :unavailable, fetch_activity.error

        assert_equal 2, calls.call,
          "an error result must not be cached"
      end
    end
  end

  test "channel_activity does not cache a not_found result" do
    with_memory_cache do
      stub_slack(->(*) { { "channel_analytics" => [], "num_found" => 0 } }) do |calls|
        assert_equal :not_found, fetch_activity.error
        fetch_activity

        assert_equal 2, calls.call
      end
    end
  end

  def windows(**over)
    Slack::Analytics.channel_windows(
      **{ channel_id: "C1", name: "general", privacy: "public",
          windows: [["2026-08-01", "2026-08-07"], ["2026-01-01", "2026-08-07"]] }.merge(over)
    )
  end

  test "channel_windows returns one result per window in the given order" do
    with_memory_cache do
      stub_slack(one_channel) do |calls|
        first, second = windows

        assert_equal 2, calls.call
        assert_equal 12, first.stats["messages_count"]
        assert_equal 12, second.stats["messages_count"]
      end
    end
  end

  test "channel_windows uses the cache only on the calling thread" do
    with_memory_cache do
      stub_slack(one_channel) do |_calls|
        test_thread = Thread.current
        cache_threads = Queue.new
        store = Rails.cache
        recorder = Class.new(SimpleDelegator) do
          define_method(:read) { |*a, **k| cache_threads << Thread.current; __getobj__.read(*a, **k) }
          define_method(:write) { |*a, **k| cache_threads << Thread.current; __getobj__.write(*a, **k) }
        end.new(store)

        Rails.cache = recorder
        windows
        Rails.cache = store

        threads = []
        threads << cache_threads.pop until cache_threads.empty?

        refute_empty threads, "cache was not used"
        assert_equal [test_thread], threads.uniq,
          "cache accessed from a fetch thread"
      end
    end
  end

  test "channel_windows with cached windows does not call slack again" do
    with_memory_cache do
      stub_slack(one_channel) do |calls|
        windows
        windows

        assert_equal 2, calls.call, "second call is served from the cache"
      end
    end
  end
end

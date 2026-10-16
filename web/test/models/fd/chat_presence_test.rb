require "test_helper"

class Fd::ChatPresenceTest < ActiveSupport::TestCase
  include ActionCable::TestHelper

  setup do
    @original_cache = Rails.cache
    Rails.cache = ActiveSupport::Cache::MemoryStore.new
    @kase = make_case
  end

  teardown { Rails.cache = @original_cache }

  test "join and leave update present_user_ids" do
    Fd::ChatPresence.join(@kase.id, "UME")
    Fd::ChatPresence.join(@kase.id, "UYOU")
    assert_equal %w[UME UYOU], Fd::ChatPresence.present_user_ids(@kase.id).sort

    Fd::ChatPresence.leave(@kase.id, "UME")
    assert_equal %w[UYOU], Fd::ChatPresence.present_user_ids(@kase.id)
  end

  test "present_user_ids keeps a user joined twice until both leave" do
    2.times { Fd::ChatPresence.join(@kase.id, "UME") }
    Fd::ChatPresence.leave(@kase.id, "UME")
    assert_equal %w[UME], Fd::ChatPresence.present_user_ids(@kase.id)

    Fd::ChatPresence.leave(@kase.id, "UME")
    assert_empty Fd::ChatPresence.present_user_ids(@kase.id)
  end

  test "leave without a prior join keeps present_user_ids empty" do
    Fd::ChatPresence.leave(@kase.id, "UME")
    assert_empty Fd::ChatPresence.present_user_ids(@kase.id)
  end

  test "present_user_ids drops a user that sent no heartbeat within the timeout" do
    Fd::ChatPresence.join(@kase.id, "UME")
    Fd::ChatPresence.join(@kase.id, "UYOU")

    travel 60.seconds do
      Fd::ChatPresence.heartbeat(@kase.id, "UYOU")
      assert_equal %w[UME UYOU], Fd::ChatPresence.present_user_ids(@kase.id).sort
    end

    travel 100.seconds do
      assert_equal %w[UYOU], Fd::ChatPresence.present_user_ids(@kase.id), "UME sent no heartbeat"
    end
  end

  test "present_user_ids returns empty for a cache entry in the pre-heartbeat format" do
    Rails.cache.write("chat_presence/#{@kase.id}", { "UOLD" => 1 })
    assert_empty Fd::ChatPresence.present_user_ids(@kase.id)

    Fd::ChatPresence.join(@kase.id, "UME")
    assert_equal %w[UME], Fd::ChatPresence.present_user_ids(@kase.id)
  end

  test "heartbeat adds a user missing from the cache" do
    Fd::ChatPresence.heartbeat(@kase.id, "UME")
    assert_equal %w[UME], Fd::ChatPresence.present_user_ids(@kase.id)
  end

  test "join and leave broadcast once each and heartbeat does not broadcast" do
    assert_broadcasts("case_#{@kase.id}_chat", 1) { Fd::ChatPresence.join(@kase.id, "UME") }
    assert_broadcasts("case_#{@kase.id}_chat", 0) { Fd::ChatPresence.heartbeat(@kase.id, "UME") }
    assert_broadcasts("case_#{@kase.id}_chat", 1) { Fd::ChatPresence.leave(@kase.id, "UME") }
  end
end

require "test_helper"

class Fd::ThreadMessageTest < ActiveSupport::TestCase
  test "fd.thread_messages is read only" do
    assert_read_only! "fd.thread_messages"
  end

  test "for_threads with no threads returns no rows" do
    assert_empty Fd::ThreadMessage.for_threads([]).to_a
  end

  test "for_threads builds one query covering all threads with one ORDER BY" do
    kase = make_case
    primary_thread = Fd::CaseThread.create!(case_id: kase.id, channel_id: "C0LOUNGE",
      thread_ts: "1754487721.123456", added_by: "UFF1", is_primary: true)
    second_thread = Fd::CaseThread.create!(case_id: kase.id, channel_id: "C0SHIP",
      thread_ts: "1754570000.100000", added_by: "UFF1")

    sql = Fd::ThreadMessage.for_threads([primary_thread, second_thread]).to_sql

    assert_includes sql, "C0LOUNGE"
    assert_includes sql, "C0SHIP"
    assert_equal 1, sql.scan(/ORDER BY/).size
    assert_empty Fd::ThreadMessage.for_threads([primary_thread, second_thread]).to_a
  end

  test "for_threads includes a duplicate thread once in the sql" do
    kase = make_case
    duplicate_threads = Array.new(2) do
      Fd::CaseThread.new(channel_id: "C0LOUNGE", thread_ts: "1754487721.123456",
        case_id: kase.id, added_by: "UFF1")
    end

    assert_equal 1, Fd::ThreadMessage.for_threads(duplicate_threads).to_sql.scan("C0LOUNGE").size
  end
end

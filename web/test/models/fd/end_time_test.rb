require "test_helper"

module Fd
  class EndTimeTest < ActiveSupport::TestCase
    test "read with no date and no time has no end" do
      assert_equal [nil, nil], EndTime.read("", "")
    end

    test "read with a date only ends at the end of that day" do
      ends, error = EndTime.read("2026-11-02", "")

      assert_nil error
      assert_equal Time.utc(2026, 11, 2, 23, 59, 59), ends.change(usec: 0)
    end

    test "read with a date and time ends at that time in utc" do
      assert_equal [Time.utc(2026, 11, 2, 14, 30), nil], EndTime.read("2026-11-02", "14:30:00")
    end

    test "read with an invalid date returns an error containing the input" do
      assert_equal [nil, "the ninth is not a date"], EndTime.read("the ninth", "")
    end

    test "read with a time and no date returns the enter a date error" do
      assert_equal [nil, "Enter a date for the end time"], EndTime.read("", "14:30")
    end
  end
end

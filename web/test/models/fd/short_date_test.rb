require "test_helper"

class Fd::ShortDateTest < ActiveSupport::TestCase
  TODAY = Date.new(2026, 10, 15)

  test "for in current year omits year" do
    assert_equal "15 Oct", Fd::ShortDate.for(Time.utc(2026, 10, 15, 12), today: TODAY)
  end

  test "for in next year includes year" do
    assert_equal "15 Oct 2027", Fd::ShortDate.for(Time.utc(2027, 10, 15, 12), today: TODAY)
  end

  test "for in past year includes year" do
    assert_equal "3 Mar 2024", Fd::ShortDate.for(Date.new(2024, 3, 3), today: TODAY)
  end

  test "for defaults today to Date.current" do
    travel_to Time.utc(2027, 1, 2, 12) do
      assert_equal "15 Oct 2026", Fd::ShortDate.for(Time.utc(2026, 10, 15, 12))
    end
  end
end

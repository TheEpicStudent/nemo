require "test_helper"

class Analytics::MartMonthlyCohortsTest < ActiveSupport::TestCase
  def cohort(month)
    Analytics::MartMonthlyCohorts.new(cohort_month: month)
  end

  test "mature? is false for the current month" do
    assert_not cohort(Date.current.beginning_of_month).mature?,
      "current month cohort is under 30 days old"
  end

  test "mature? is true for an old cohort month" do
    old = (Date.current - 120).beginning_of_month

    assert cohort(old).mature?
  end

  test "mature? flips 30 days after the month ends" do
    month = (Date.current - 60).beginning_of_month
    closes = month.end_of_month

    travel_to(closes + 29) { assert_not cohort(month).mature? }
    travel_to(closes + 30) { assert cohort(month).mature? }
  end

  test "matures_on returns the month end plus 30 days" do
    month = Date.new(2026, 8, 1)

    assert_equal Date.new(2026, 9, 30), cohort(month).matures_on
  end
end

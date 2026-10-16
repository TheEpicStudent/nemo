require "test_helper"

class Analytics::MartCohortSurvivalTest < ActiveSupport::TestCase
  def curve(shares)
    Analytics::MartCohortSurvival::Curve.new(cohort_month: Date.new(2026, 4, 1), members: 100,
      shares: shares)
  end

  test "Curve#last_filled_index returns the last non-nil index" do
    assert_equal 2, curve([100.0, 80.0, 60.0, nil, nil]).last_filled_index
  end

  test "Curve#partial? is false with a full horizon and true with missing days" do
    horizon = (0..3).to_a

    assert_not curve([100.0, 80.0, 60.0, 40.0]).partial?(horizon)
    assert curve([100.0, 80.0, nil, nil]).partial?(horizon)
  end

  test "Curve#at returns nil for an unobserved day" do
    assert_nil curve([100.0, nil]).at(1)
  end

  test "survival shares do not increase over time" do
    shares = [100.0, 74.0, 52.0, 28.0]

    assert_equal shares, shares.sort.reverse, "shares must not increase"
  end
end

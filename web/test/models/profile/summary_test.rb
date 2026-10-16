require "test_helper"

class Profile::SummaryTest < ActiveSupport::TestCase
  include SeedsPipelineTables

  IDLE = "UIDLEONE".freeze

  def loaded!(source, on)
    as_pipeline("INSERT INTO raw.analytics_day (source, ds, loaded) VALUES (?, ?, true) " \
                "ON CONFLICT (source, ds) DO UPDATE SET loaded = true", source, on)
    seeded!("raw.analytics_day", "ds", on)
  end

  def summary_with_member_since(on)
    Profile::Summary.new(IDLE).tap do |summary|
      summary.define_singleton_method(:member_since) { on }
    end
  end

  test "slack stats for loaded days without activity are zero" do
    loaded!("member_day", Date.new(2020, 1, 15))

    stats = Profile::Summary.new(IDLE).slack(Date.new(2020, 1, 10), Date.new(2020, 1, 20))

    assert_equal 0, stats[:days_active]
    assert_equal 0, stats[:messages]
  end

  test "slack stats for member_day_import loaded days without activity are zero" do
    loaded!("member_day_import", Date.new(2020, 3, 4))

    stats = Profile::Summary.new(IDLE).slack(Date.new(2020, 3, 1), Date.new(2020, 3, 7))

    assert_equal 0, stats[:days_active]
  end

  test "slack stats days_active is nil when no day in range is loaded" do
    loaded!("member_day", Date.new(2020, 1, 15))

    assert_nil Profile::Summary.new(IDLE).slack(Date.new(2019, 6, 1), Date.new(2019, 6, 30))[:days_active]
  end

  test "slack stats days_active is nil when range precedes member_since" do
    loaded!("member_day", Date.new(2020, 1, 15))

    stats = summary_with_member_since(Time.utc(2020, 2, 1)).slack(Date.new(2020, 1, 10), Date.new(2020, 1, 20))

    assert_nil stats[:days_active]
  end

  test "floor is the first loaded day on or after member_since" do
    loaded!("member_day", Date.new(2020, 1, 15))
    loaded!("member_day", Date.new(2020, 2, 3))

    assert_equal Date.new(2020, 2, 3), summary_with_member_since(Time.utc(2020, 2, 1)).floor
  end
end

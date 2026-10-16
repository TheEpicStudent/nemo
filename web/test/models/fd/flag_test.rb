require "test_helper"

module Fd
  class FlagTest < ActiveSupport::TestCase
    setup do
      Flag.delete_all
      Current.forget_flags
    end

    teardown do
      Flag.delete_all
      Current.forget_flags
    end

    test "on? and showing use the file defaults without rows" do
      assert Flag.on?(:fire_engine)
      assert Flag.on?("analytics")
      assert_equal %w[analytics fire_engine], Flag.showing
    end

    test "TABLE rows have a default key and no boolean key" do
      Flag::KEYS.each do |key|
        row = Flag::TABLE.fetch(key)
        assert row.key?("default"), "#{key} has no default"
        assert_not row.key?(true), "yaml read the key as a boolean, use default: not on:"
      end
    end

    test "set! false for fire_engine leaves analytics on" do
      Flag.set!(:fire_engine, false, by: "UME")

      assert Flag.off?(:fire_engine)
      assert Flag.on?(:analytics)
      assert_equal %w[analytics], Flag.showing
    end

    test "set! true after false turns the flag on with a single row" do
      Flag.set!(:fire_engine, false, by: "UME")
      Flag.set!(:fire_engine, true, by: "UME")

      assert Flag.on?(:fire_engine)
      assert_equal 1, Flag.where(key: "fire_engine").count, "one row per key"
    end

    test "set! stores changed_by and changed_at" do
      row = Flag.set!(:analytics, false, by: "UBOSS")

      assert_equal "UBOSS", row.changed_by
      assert_not_nil row.changed_at
    end

    test "on? and set! raise UnknownError for an unknown key" do
      assert_raises(Flag::UnknownError) { Flag.on?(:teleporter) }
      assert_raises(Flag::UnknownError) { Flag.set!(:teleporter, true, by: "UME") }
    end

    test "every flag has a label and covers text" do
      Flag::KEYS.each do |key|
        assert Flag.label(key).present?
        assert Flag.covers(key).present?
      end
    end

    test "on? is cached until Current.forget_flags" do
      assert Flag.on?(:fire_engine)
      Flag.insert!({ key: "fire_engine", is_on: false, changed_by: "UME",
                     changed_at: Time.current })

      assert Flag.on?(:fire_engine), "cached value returned after the row changed"

      Current.forget_flags
      assert Flag.off?(:fire_engine)
    end
  end
end

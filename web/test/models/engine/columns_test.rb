require "test_helper"

module Engine
  class ColumnsTest < ActiveSupport::TestCase
    setup { Engine::Columns.reset! }
    teardown { Engine::Columns.reset! }

    test "has? returns true for an existing column" do
      assert Engine::Columns.has?(:fct_ingest_run, :status)
      assert Engine::Columns.has?("fct_ingest_run", "rows_in")
    end

    test "has? returns false for a missing column without raising" do
      assert_not Engine::Columns.has?(:fct_ingest_run, :coverage_ratio)
    end

    test "names returns empty and has? returns false for a missing relation" do
      assert_equal [], Engine::Columns.names(:no_such_view)
      assert_not Engine::Columns.has?(:no_such_view, :anything)
    end

    test "names returns the same array on repeated calls" do
      first = Engine::Columns.names(:fct_ingest_run)
      assert_same first, Engine::Columns.names(:fct_ingest_run)
    end
  end
end

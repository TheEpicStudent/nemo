require "test_helper"

class Channels::FilterTest < ActiveSupport::TestCase
  def build(rows, match: nil)
    Channels::Filter.new(rows: rows, match: match)
  end

  test "clause binds a numeric value as a parameter" do
    f = build([{ "f" => "members", "op" => "gt", "v" => ["1000"] }])
    sql, *binds = f.clause

    assert_equal "r.total_members > ?", sql
    assert_equal [1000], binds
  end

  test "non numeric values produce no condition and no clause" do
    %w[1000);DROP 1e9 abc " 12abc].each do |bad|
      f = build([{ "f" => "members", "op" => "gt", "v" => [bad] }])
      assert_empty f.conditions, "#{bad.inspect} must not survive coercion"
      assert_nil f.clause
    end
  end

  test "unknown field or operator produces no condition" do
    assert_empty build([{ "f" => "total_members", "op" => "gt", "v" => ["1"] }]).conditions
    assert_empty build([{ "f" => "members", "op" => "drop", "v" => ["1"] }]).conditions
    assert_empty build([{ "f" => "members", "op" => "contains", "v" => ["1"] }]).conditions,
      "an operator from another kind must not apply"
  end

  test "between sorts its two values in the binds and in the label" do
    f = build([{ "f" => "members", "op" => "between", "v" => %w[900 100] }])
    sql, *binds = f.clause

    assert_equal "r.total_members BETWEEN ? AND ?", sql
    assert_equal [100, 900], binds
    assert_equal "Members is between 100 and 900", f.conditions.first.label
  end

  test "between with one value produces no condition" do
    assert_empty build([{ "f" => "members", "op" => "between", "v" => ["100"] }]).conditions
  end

  test "unset needs no value and builds a last_message_at IS NULL clause" do
    f = build([{ "f" => "last_post", "op" => "unset", "v" => [] }])

    assert_equal 1, f.size
    assert_equal ["(r.channel_id IS NOT NULL AND r.last_message_at IS NULL)"], f.clause
  end

  test "contains escapes LIKE wildcards in the bind" do
    f = build([{ "f" => "name", "op" => "contains", "v" => ["100%_a"] }])
    _sql, bind = f.clause

    assert_equal "%100\\%\\_a%", bind
  end

  test "match all and unknown values join with AND and match any joins with OR" do
    rows = [
      { "f" => "members", "op" => "gt", "v" => ["10"] },
      { "f" => "posters", "op" => "lt", "v" => ["5"] }
    ]

    assert_includes build(rows).clause.first, " AND "
    assert_includes build(rows, match: "any").clause.first, " OR "
    assert_includes build(rows, match: "sideways").clause.first, " AND "
  end

  test "within binds an integer day count" do
    f = build([{ "f" => "last_post", "op" => "within", "v" => ["90"] }])
    sql, *binds = f.clause

    assert_equal "r.last_message_at >= now() - (? || ' days')::interval", sql
    assert_equal [90], binds
  end

  test "after parses an ISO date into a Date bind" do
    f = build([{ "f" => "created", "op" => "after", "v" => ["2026-01-31"] }])
    _sql, bind = f.clause

    assert_equal Date.new(2026, 1, 31), bind
  end

  test "conditions are capped at MAX_CONDITIONS" do
    rows = Array.new(30) { { "f" => "members", "op" => "gt", "v" => ["1"] } }

    assert_equal Channels::Filter::MAX_CONDITIONS, build(rows).size
  end

  test "condition label describes gt and between and within operators" do
    assert_equal "Members is over 10",
      build([{ "f" => "members", "op" => "gt", "v" => ["10"] }]).conditions.first.label
    assert_equal "Poster share is between 2% and 10%",
      build([{ "f" => "spoke", "op" => "between", "v" => %w[10 2] }]).conditions.first.label
    assert_equal "Last post is within the last 90 days",
      build([{ "f" => "last_post", "op" => "within", "v" => ["90"] }]).conditions.first.label
  end

  test "from parses conditions keyed by index" do
    params = ActionController::Parameters.new(
      "match" => "all",
      "c" => { "898" => { "f" => "members", "op" => "gt", "v" => ["10000", ""] } }
    )
    f = Channels::Filter.from(params)

    assert_equal 1, f.size, "an index-keyed hash of rows must parse"
    assert_equal ["r.total_members > ?", 10_000], f.clause
  end

  test "from parses a plain list of conditions" do
    params = ActionController::Parameters.new(
      "c" => [{ "f" => "members", "op" => "lt", "v" => ["5"] }]
    )

    assert_equal ["r.total_members < ?", 5], Channels::Filter.from(params).clause
  end

  test "from with empty params gives no conditions" do
    assert_empty Channels::Filter.from(ActionController::Parameters.new).conditions
  end

  test "measures override replaces the column for one field only" do
    params = ActionController::Parameters.new(
      "c" => { "0" => { "f" => "messages", "op" => "gt", "v" => ["100"] },
               "1" => { "f" => "members", "op" => "gt", "v" => ["10"] } }
    )
    f = Channels::Filter.from(params, measures: { "messages" => "a.range_messages" })

    assert_equal ["a.range_messages > ? AND r.total_members > ?", 100, 10], f.clause
  end

  test "measures override does not add a field outside FIELDS" do
    params = ActionController::Parameters.new(
      "c" => [{ "f" => "spend", "op" => "gt", "v" => ["1"] }]
    )

    assert_empty Channels::Filter.from(params, measures: { "spend" => "1=1" }).conditions
  end

  test "unset on a measures override tests the override alias for NULL" do
    f = Channels::Filter.from(
      ActionController::Parameters.new("c" => [{ "f" => "messages", "op" => "unset", "v" => [] }]),
      measures: { "messages" => "a.range_messages" }
    )

    assert_equal ["a.range_messages IS NULL"], f.clause
  end

  test "every FIELDS kind has an OPS entry" do
    Channels::Filter::FIELDS.each do |field|
      assert Channels::Filter::OPS.key?(field.kind), "#{field.key} has no operator set"
    end
  end
end

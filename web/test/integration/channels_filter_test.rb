require "test_helper"

class ChannelsFilterTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UCHAN", "analytics")
    sign_in_as(@me)
  end

  def get_channels(**params)
    get channels_path(params)
  end

  def value_for(field, op)
    return "a" if field.kind == :text
    return "30" if field.kind == :date && Channels::Filter::DAY_COUNT_OPS.include?(op)
    return "2026-01-01" if field.kind == :date

    "1"
  end

  def every_field_and_op
    Channels::Filter::FIELDS.flat_map do |field|
      field.ops.keys.map { |op| [field, op] }
    end
  end

  test "index returns 200 for every filter field and operator" do
    pairs = every_field_and_op
    refute_empty pairs, "no filter fields defined"

    broken = pairs.reject do |field, op|
      arity = Channels::Filter::OPS.fetch(field.kind).fetch(op).last
      values = Array.new(arity) { value_for(field, op) }
      get_channels(c: { "0" => { "f" => field.key, "op" => op, "v" => values } })
      response.status == 200
    end

    assert_empty broken.map { |field, op| "#{field.key} #{op} => #{response.status}" }
  end

  test "index with date within filter given one value returns 200" do
    get_channels(c: { "0" => { "f" => "created", "op" => "within", "v" => ["2026-01-01"] } })

    assert_response :success
  end

  test "index with first window preset returns 200" do
    get_channels(days: Channels::Window::PRESETS.first)

    assert_response :success
  end

  test "index returns 200 for every SORT_SQL key" do
    refute_empty ChannelsController::SORT_SQL

    broken = ChannelsController::SORT_SQL.keys.reject do |key|
      get_channels(sort: key, direction: "asc")
      response.status == 200
    end

    assert_empty broken, "sort keys not returning 200: #{broken.join(', ')}"
  end
end

require "test_helper"

class Fd::ChatPeopleTest < ActiveSupport::TestCase
  Row = Struct.new(:body, :blocks, keyword_init: true)

  test "ids reads user ids from row blocks" do
    row = Row.new(blocks: [{ "type" => "rich_text", "elements" => [
      { "type" => "rich_text_section", "elements" => [
        { "type" => "text", "text" => "ask " },
        { "type" => "user", "user_id" => "U0FROMBLOCK" }
      ] }
    ] }])

    assert_equal ["U0FROMBLOCK"], Fd::ChatPeople.ids(row)
  end

  test "ids parses user mentions from row body when blocks are nil" do
    row = Row.new(body: "ask <@U0FROMBODY> about it")

    assert_equal ["U0FROMBODY"], Fd::ChatPeople.ids(row)
  end

  test "ids deduplicates across rows and groups" do
    rows = [Row.new(body: "<@U0SAME0000>"), Row.new(body: "<@U0SAME0000> and <@U0OTHER000>")]

    assert_equal %w[U0SAME0000 U0OTHER000], Fd::ChatPeople.ids(rows, [nil])
  end

  test "ids returns an empty array for empty rows and nil" do
    assert_equal [], Fd::ChatPeople.ids([], nil)
  end
end

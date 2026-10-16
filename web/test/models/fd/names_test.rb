require "test_helper"

class Fd::NamesTest < ActiveSupport::TestCase
  def seeded = Fd::Member.order(:user_id).first

  test "for resolves a member to its name and known? is true" do
    names = Fd::Names.for([seeded.user_id])
    assert_equal seeded.name, names[seeded.user_id]
    assert names.known?(seeded.user_id)
  end

  test "[] falls back to the handle for a blank display_name" do
    names = Fd::Names.new(
      members: { "U1" => Fd::Member.new(user_id: "U1", display_name: "", handle: "ada") }
    )
    assert_equal "ada", names["U1"]
  end

  test "[] returns @user_id for an unknown member or one without a name or handle" do
    assert_equal "@U1", Fd::Names.none["U1"]
    assert Fd::Names.none.unknown?("U1")
    assert_equal "@U1", Fd::Names.new(
      members: { "U1" => Fd::Member.new(user_id: "U1", display_name: "", handle: "") }
    )["U1"]
  end

  test "unknown? is false for a member with a display_name and for nil" do
    names = Fd::Names.new(members: { "U1" => Fd::Member.new(user_id: "U1", display_name: "Ada") })
    assert_not names.unknown?("U1")
    assert_not Fd::Names.none.unknown?(nil)
  end

  test "[] returns n/a for nil and blank ids" do
    assert_equal "n/a", Fd::Names.none[nil]
    assert_equal "n/a", Fd::Names.none[""]
  end

  test "for returns non member ids unchanged without querying" do
    queries = 0
    counter = ->(*, payload) { queries += 1 unless payload[:name] == "SCHEMA" }

    names = ActiveSupport::Notifications.subscribed(counter, "sql.active_record") do
      Fd::Names.for(%w[migration seed dev:people])
    end

    assert_equal 0, queries, "provenance strings are not members"
    assert_equal "migration", names["migration"]
    assert_equal "dev:people", names["dev:people"]
  end

  test "list joins known and unknown names with and" do
    names = Fd::Names.new(members: { "U1" => Fd::Member.new(user_id: "U1", display_name: "Ada") })
    assert_equal "Ada and @U2", names.list(%w[U1 U2])
    assert_equal "Ada", names.list(["U1"])
    assert_equal "", names.list([])
  end

  test "for loads 20 members in one query" do
    ids = Fd::Member.order(:user_id).limit(20).pluck(:user_id)
    queries = 0
    counter = ->(*, payload) { queries += 1 unless payload[:name] == "SCHEMA" }

    ActiveSupport::Notifications.subscribed(counter, "sql.active_record") do
      Fd::Names.for(ids)
    end

    assert_equal 1, queries, "one query for the members"
  end

  test "member returns the Fd::Member row and nil for an unknown id" do
    names = Fd::Names.for([seeded.user_id])
    assert_equal seeded.user_id, names.member(seeded.user_id).user_id
    assert_nil names.member("UNOBODY")
  end
end

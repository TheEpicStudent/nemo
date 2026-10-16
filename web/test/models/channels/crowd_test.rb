require "test_helper"

class Channels::CrowdTest < ActiveSupport::TestCase
  def snapshot(members:, posted:, viewed:)
    Analytics::MartChannelRange.new(total_members: members, members_who_posted: posted,
      members_who_viewed: viewed)
  end

  def channel_members = Channels::Crowd.new("C1")

  test "composition returns spoke read and never parts with people and share" do
    parts = channel_members.composition(snapshot(members: 1000, posted: 100, viewed: 400))

    assert_equal %w[spoke read never], parts.map(&:key)
    assert_equal [100, 300, 600], parts.map(&:people)
    assert_equal [10.0, 30.0, 60.0], parts.map(&:share)
  end

  test "composition with more viewers than members has no negative people count" do
    parts = channel_members.composition(snapshot(members: 100, posted: 90, viewed: 400))

    assert_equal [90, 10, 0], parts.map(&:people)
    assert parts.none? { |part| part.people.negative? }
  end

  test "composition with fewer viewers than posters counts viewers as posters" do
    parts = channel_members.composition(snapshot(members: 100, posted: 40, viewed: 10))

    assert_equal [40, 0, 60], parts.map(&:people)
  end

  test "composition with a nil snapshot or zero members returns empty" do
    assert_empty channel_members.composition(nil)
    assert_empty channel_members.composition(snapshot(members: 0, posted: 0, viewed: 0))
  end

  test "TENURE has a label for every TENURE_ORDER band" do
    assert_equal Channels::Crowd::TENURE.keys.sort, Channels::Crowd::TENURE_ORDER.sort
    assert Channels::Crowd::TENURE.values.all?(&:present?)
  end
end

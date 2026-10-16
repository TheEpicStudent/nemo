require "test_helper"

class Channels::PostsTest < ActiveSupport::TestCase
  setup do
    @row = Analytics::FctMessage.where(is_reply: false, subtype: nil)
      .where.not(author_id: nil).where("author_id ~ '^[UW]'").order(:posted_at).first
    skip "seed has no top-level post" if @row.nil?
    @channel_id = @row.channel_id
    @subject_id = @row.author_id
  end

  def subject_posts(limit: Channels::Posts::POST_LIMIT)
    Channels::Posts.rows(channel_id: @channel_id, subject_id: @subject_id, limit: limit)
  end

  test "POST_LIMIT is 3 and rows returns at most 3" do
    assert_equal 3, Channels::Posts::POST_LIMIT
    assert_operator subject_posts.size, :<=, 3
  end

  test "rows returns only posts by subject_id" do
    assert subject_posts.all? { |row| row.author_id == @subject_id }
  end

  test "rows excludes replies" do
    assert subject_posts.none?(&:is_reply)
  end

  test "rows orders by posted_at desc" do
    stamps = subject_posts.map(&:posted_at)
    assert_equal stamps.sort.reverse, stamps
  end

  test "rows for another author excludes subject posts" do
    other = Analytics::FctMessage.where(channel_id: @channel_id, is_reply: false)
      .where.not(author_id: [@subject_id, nil]).first
    skip "seed has no other author in channel" if other.nil?

    assert Channels::Posts.rows(channel_id: @channel_id, subject_id: other.author_id)
      .none? { |row| row.author_id == @subject_id }
  end

  test "rows returns only posts from channel_id" do
    assert subject_posts.all? { |row| row.channel_id == @channel_id }
  end

  Viewer = Struct.new(:user_id)

  test "may_read? allows viewer own user_id only" do
    assert Channels::Posts.may_read?(Viewer.new("U1"), "U1")
    assert_not Channels::Posts.may_read?(Viewer.new("U1"), "U2")
    assert_not Channels::Posts.may_read?(nil, "U1")
    assert_not Channels::Posts.may_read?(Viewer.new("U1"), nil)
  end

  Row = Struct.new(:channel_id, :ts, :author_id, :posted_at, :reply_count, :reaction_count)

  def stub_posts(rows, message_lookup)
    original_rows = Channels::Posts.method(:rows)
    Channels::Posts.define_singleton_method(:rows) { |**| rows }
    original_at = Slack::Message.method(:at)
    Slack::Message.define_singleton_method(:at) { |channel_id, ts| message_lookup.call(channel_id, ts) }
    yield
  ensure
    Channels::Posts.define_singleton_method(:rows, original_rows)
    Slack::Message.define_singleton_method(:at, original_at)
  end

  def build_row(ts = "1790701062.123456")
    Row.new("C1", ts, "U1", Time.current, 2, 5)
  end

  test "for looks up each row message through Slack::Message.at" do
    lookups = []
    result = Slack::Message::Result.new(message: { "text" => "big news" })

    stub_posts([build_row], ->(channel_id, ts) { lookups << [channel_id, ts]; result }) do
      posts = Channels::Posts.for(channel_id: "C1", subject_id: "U1")

      assert_equal [["C1", "1790701062.123456"]], lookups
      assert_equal "big news", posts.sole.message["text"]
      assert_equal 2, posts.sole.replies
      assert_equal 5, posts.sole.reactions
      assert_equal "U1", posts.sole.author_id
    end
  end

  test "for drops row when message lookup returns not_found" do
    stub_posts([build_row], ->(*) { Slack::Message::Result.new(error: :not_found) }) do
      assert_empty Channels::Posts.for(channel_id: "C1", subject_id: "U1")
    end
  end

  test "for keeps row with unavailable error and nil message" do
    stub_posts([build_row], ->(*) { Slack::Message::Result.new(error: :unavailable) }) do
      posts = Channels::Posts.for(channel_id: "C1", subject_id: "U1")

      assert_equal :unavailable, posts.sole.error
      assert_nil posts.sole.message
    end
  end
end

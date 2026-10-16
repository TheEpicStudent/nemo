require "test_helper"

class ChannelPostsTest < ActionDispatch::IntegrationTest
  MESSAGE = {
    "ts" => nil, "text" => "big news <@UMENTION>",
    "blocks" => [{ "type" => "rich_text", "elements" => [
      { "type" => "rich_text_section", "elements" => [
        { "type" => "text", "text" => "big news " },
        { "type" => "user", "user_id" => "UMENTION" }
      ] }
    ] }]
  }.freeze

  RANGE = { "start_date" => "2026-01-01", "end_date" => "2026-12-31" }.freeze
  NO_ANALYTICS = { "channel_analytics" => [] }.freeze

  setup do
    @post = Analytics::FctMessage.where(is_reply: false, subtype: nil)
      .where.not(author_id: nil).where("author_id ~ '^[UW]'").order(posted_at: :desc).first
    skip "seed has no top-level post" if @post.nil?

    @me = grant_role!(@post.author_id, "analytics")
    sign_in_as(@me)
    Rails.cache.clear
  end

  teardown do
    Channels::Activity::Setting.where(channel_id: @post&.channel_id).delete_all
  end

  def enable_activity!
    Channels::Activity::Setting.create!(channel_id: @post.channel_id, set_by: "test",
      set_at: Time.current)
  end

  def stub_slack(reply)
    original_call = Slack::ProxyClient.method(:call)
    calls = []
    Slack::ProxyClient.define_singleton_method(:call) do |method, params = {}, **|
      next RANGE if method == "admin.analytics.getAvailableDateRange"
      next NO_ANALYTICS if method == "admin.analytics.getChannelAnalytics"

      calls << [method, params]
      reply.call(method, params)
    end
    yield calls
  ensure
    Slack::ProxyClient.define_singleton_method(:call, original_call)
  end

  def one_post
    ->(_method, params) { { "ok" => true, "messages" => [MESSAGE.merge("ts" => params["latest"])] } }
  end

  def get_channel(**params) = get channel_path(@post.channel_id, **params)

  test "channel show without activity setting has no posts tab link" do
    stub_slack(->(*) { flunk "slack called without posts tab" }) do
      get_channel

      assert_response :success
      assert_no_match(/view=posts/, response.body)
    end
  end

  test "channel show view posts without activity setting renders overview" do
    stub_slack(->(*) { flunk "slack called without posts tab" }) do
      get_channel(view: "posts")

      assert_response :success
      assert_match(/aria-current="true"[^>]*>\s*Overview|Overview\s*<\/a>/, response.body)
      assert_no_match(/No posts/, response.body)
    end
  end

  test "channel show with activity setting has posts tab link" do
    enable_activity!
    stub_slack(one_post) { get_channel }

    assert_response :success
    assert_match(/view=posts/, response.body)
  end

  test "posts view renders message text from conversations.history" do
    enable_activity!
    stub_slack(one_post) do |calls|
      get_channel(view: "posts")

      assert_response :success
      assert_match(/big news/, response.body)
      assert_equal ["conversations.history"], calls.map(&:first).uniq
      assert_operator calls.size, :<=, Channels::Posts::POST_LIMIT
      assert_operator calls.size, :>=, 1
    end
  end

  test "posts view requests at most 3 messages and renders Message activity" do
    enable_activity!
    stub_slack(one_post) do |calls|
      get_channel(view: "posts")

      assert_operator calls.size, :<=, 3
      assert_match(/Message activity/, response.body)
    end
  end

  test "posts view links each post to its message activity page" do
    enable_activity!
    stub_slack(one_post) do
      get_channel(view: "posts")

      assert_match(/href="\/messages\/#{@post.channel_id}\/#{Regexp.escape(@post.ts)}"/,
        response.body)
    end
  end

  test "posts view excludes posts by other authors" do
    enable_activity!
    other = Analytics::FctMessage.where(channel_id: @post.channel_id, is_reply: false)
      .where.not(author_id: [@post.author_id, nil]).where("author_id ~ '^[UW]'").first
    skip "seed has no other author in channel" if other.nil?

    stub_slack(one_post) do |calls|
      get_channel(view: "posts")

      assert_no_match(/#{Regexp.escape(other.ts)}/, response.body)
      assert calls.none? { |_, params| params["latest"] == other.ts }
    end
  end

  test "posts view with unavailable slack proxy renders Message unavailable" do
    enable_activity!
    stub_slack(->(*) { raise Slack::ProxyClient::UnavailableError, "proxy returned 503" }) do
      get_channel(view: "posts")

      assert_response :success
      assert_match(/Message unavailable/, response.body)
    end
  end
end

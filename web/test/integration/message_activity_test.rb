require "test_helper"

class MessageActivityTest < ActionDispatch::IntegrationTest
  STATS = {
    "ok" => true,
    "stats" => {
      "num_users_viewed" => 224, "num_users_clicked" => 58, "num_users_reacted" => 12,
      "num_shares" => 0, "top_threaded_reply_by_reactions_ts" => "1790701348.867479",
      "viewers_time_series" => { "data" => [
        { "seriesType" => "1h", "series" => [
          { "value" => 1_790_701_062_000_000, "count" => 0 },
          { "value" => 1_790_701_122_000_000, "count" => 3 }
        ] },
        { "seriesType" => "1d", "series" => [
          { "value" => 1_790_701_062_000_000, "count" => 0 },
          { "value" => 1_790_701_962_000_000, "count" => 23 },
          { "value" => 1_790_702_862_000_000, "count" => 14 }
        ] }
      ] },
      "client_breakdown" => { "desktop_count" => 75, "browser_count" => 123, "mobile_count" => 26 }
    }
  }.freeze

  setup do
    @post = Analytics::FctMessage.where(is_reply: false).where.not(author_id: nil)
      .where("author_id ~ '^[UW]'").order(:posted_at).first
    skip "seed has no top-level post" if @post.nil?
    @author = Account.find_or_create_by!(user_id: @post.author_id)
    @path = message_activity_path(@post.channel_id, @post.ts)
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
      calls << [method, params]
      reply.call(method, params)
    end
    yield calls
  ensure
    Slack::ProxyClient.define_singleton_method(:call, original_call)
  end

  test "show renders author activity stats from insights.messageStats" do
    enable_activity!
    sign_in_as(@author)

    stub_slack(->(*) { STATS }) do |calls|
      get @path

      assert_response :success
      assert_includes calls,
        ["insights.messageStats", { "channel" => @post.channel_id, "ts" => @post.ts }]
      assert_includes calls.map(&:first), "conversations.history"
    end
    assert_includes response.body, "224"
    assert_includes response.body, "Reach over time"
    assert_includes response.body, "new viewers"
    assert_includes response.body, "browser"
  end

  test "show with span 1h marks First hour current" do
    enable_activity!
    sign_in_as(@author)

    stub_slack(->(*) { STATS }) do
      get "#{@path}?span=1h"
    end

    assert_response :success
    assert_match(/aria-current="true"[^>]*>First hour|First hour<\/a>/, response.body)
  end

  test "show for a non-author redirects to root without a Slack call" do
    enable_activity!
    sign_in_as(Account.find_or_create_by!(user_id: "UMSGOTHER"))

    stub_slack(->(*) { flunk "unexpected Slack call for a non-author" }) do
      get @path
    end

    assert_redirected_to root_path
    assert_match(/Own posts only/, flash[:alert])
  end

  test "show for a community manager redirects to root without a Slack call" do
    enable_activity!
    sign_in_as(grant_role!("UMSGBOSS", "community_manager"))

    stub_slack(->(*) { flunk "unexpected Slack call" }) do
      get @path
    end

    assert_redirected_to root_path
  end

  test "show without activity enabled renders Activity unavailable and no Slack call" do
    sign_in_as(@author)

    stub_slack(->(*) { flunk "unexpected Slack call for a channel without activity" }) do
      get @path
    end

    assert_response :success
    assert_includes response.body, "Activity unavailable"
    refute_includes response.body, "Reach over time"
  end

  test "show with an unknown ts renders Post not found without a Slack call" do
    enable_activity!
    sign_in_as(@author)

    stub_slack(->(*) { flunk "unexpected Slack call" }) do
      get message_activity_path(@post.channel_id, "1.000001")
    end

    assert_response :success
    assert_includes response.body, "Post not found"
  end

  test "show renders No activity when Slack raises an error" do
    enable_activity!
    sign_in_as(@author)

    stub_slack(->(*) { raise Slack::ProxyClient::Error, "down" }) do
      get @path
    end

    assert_response :success
    assert_includes response.body, "No activity"
  end

  test "show signed out redirects" do
    get @path

    assert_response :redirect
  end
end

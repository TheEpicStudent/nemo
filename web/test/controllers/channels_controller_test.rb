require "test_helper"

class ChannelsControllerTest < ActionDispatch::IntegrationTest
  teardown do
    OmniAuth.config.test_mode = false
    OmniAuth.config.mock_auth[:hackclub] = nil
  end

  def busiest_channel
    id = Analytics::MartChannelDay.group(:channel_id)
      .order(Arel.sql("count(*) desc")).limit(1).pluck(:channel_id).first
    Analytics::DimChannel.find_by(channel_id: id, archived: false) ||
      Analytics::DimChannel.where(archived: false).first
  end

  def analyst
    staff = grant_role!("UTESTCHAN1", "analytics")
    sign_in_as(staff)
    staff
  end

  test "show without view renders the overview tab and Traffic card" do
    analyst
    channel = busiest_channel

    get channel_path(channel.channel_id)

    assert_response :success
    assert_select "nav.views a.view[aria-current='true']", text: "Overview"
    assert_select "h2.card-title", text: "Traffic"
  end

  test "show with each non-overview view renders its own card and no Traffic card" do
    analyst
    channel = busiest_channel
    card_titles = {
      "activity" => "Top posters",
      "newcomers" => "First posts",
      "messages" => "Message content",
      "neighbours" => "Neighbours"
    }

    card_titles.each do |view, title|
      get channel_path(channel.channel_id, view: view)

      assert_response :success
      assert_select "h2.card-title", text: title
      assert_select "h2.card-title", text: "Traffic", count: 0
      assert_select "nav.views a.view[aria-current='true']", text: ChannelsController::VIEWS[view]
    end
  end

  test "show with unknown view renders the overview" do
    analyst
    channel = busiest_channel

    get channel_path(channel.channel_id, view: "nonsense")

    assert_response :success
    assert_select "h2.card-title", text: "Traffic"
  end

  test "show renders daterange on overview and not on activity view" do
    analyst
    channel = busiest_channel

    get channel_path(channel.channel_id)
    assert_select ".daterange", count: 1

    get channel_path(channel.channel_id, view: "activity")
    assert_select ".daterange", count: 0
  end

  test "show with days param marks the preset and adds days to tab links" do
    analyst
    channel = busiest_channel

    get channel_path(channel.channel_id, days: 7)

    assert_response :success
    assert_select ".daterange-preset", text: /Last 7 days/
    assert_select ".daterange-presets a[aria-current=true]", text: "Last 7 days"
    assert_select "nav.views a[href*='days=7']"
  end

  test "show with start and end params renders custom preset and both dates" do
    analyst
    channel = busiest_channel
    edge = Channels::Pulse.edge

    get channel_path(channel.channel_id, start: (edge - 3).iso8601, end: edge.iso8601)

    assert_response :success
    assert_select ".daterange input[name=start][value=?]", (edge - 3).iso8601
    assert_select ".daterange input[name=end][value=?]", edge.iso8601
    assert_select ".daterange-preset", text: /Custom/
    assert_select ".daterange-open", text: /#{(edge - 3).strftime("%b %-d")}/
  end

  test "show with range past warehouse data renders Traffic card" do
    analyst
    channel = busiest_channel
    edge = Channels::Pulse.edge

    get channel_path(channel.channel_id, start: edge.iso8601, end: (edge + 90).iso8601)

    assert_response :success
    assert_select "h2.card-title", text: "Traffic"
  end

  test "show activity with month param renders the selected month" do
    analyst
    channel = Analytics::DimChannel.find_by(
      channel_id: Analytics::MartChannelPerson.limit(1).pick(:channel_id)
    )
    months = Analytics::MartChannelPerson.where(channel_id: channel.channel_id)
      .distinct.order(month: :desc).pluck(:month)
    skip "one month only in this seed" unless months.many?

    get channel_path(channel.channel_id, view: "activity", month: months.second.iso8601)

    assert_response :success
    assert_select "h2.card-title", text: "Top posters"
    assert_select ".card-tools .btn", text: /#{months.second.strftime("%b %Y")}/
  end

  test "show for channel without warehouse rows renders every view" do
    analyst
    bare = Analytics::DimChannel.where(archived: false)
      .where.not(channel_id: Analytics::MartChannelDay.select(:channel_id)).first
    skip "every channel has day rows in this seed" if bare.nil?

    ChannelsController::VIEWS.each_key do |view|
      get channel_path(bare.channel_id, view: view)

      assert_response :success
    end
  end

  test "show for channel outside the audience redirects to channels list" do
    staff = Account.create!(user_id: "UTESTCHAN2")
    sign_in_as(staff)
    channel = busiest_channel

    get channel_path(channel.channel_id)

    assert_redirected_to channels_path(q: channel.channel_id)
  end

  test "show with unknown channel id redirects to channels list" do
    analyst

    get channel_path("CNOPE00000")

    assert_redirected_to channels_path(q: "CNOPE00000")
  end
end

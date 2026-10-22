require "test_helper"

class FdChatTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = grant_role!("UME", "community_manager")
    @kase = make_case
    sign_in_as(@me)
  end

  test "chats create as turbo_stream returns success" do
    post fd_case_chats_path(@kase), params: { body: "who wants this one?" },
      as: :turbo_stream

    assert_response :success
  end

  test "chat log show as html returns success" do
    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_response :success
  end

  test "chat log html has one chat-log id and a separate chat-messages container" do
    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_equal 1, response.body.scan(/id="chat-log-#{@kase.id}"/).size,
      "the frame id must not be reused by the scroll container"
    assert_includes response.body, %(id="chat-messages-#{@kase.id}" class="chatscroll")
  end

  test "chat log turbo_stream targets the chat-messages container" do
    post fd_case_chats_path(@kase), params: { body: "meow" }, as: :turbo_stream
    get fd_case_chat_log_path(@kase, since: "0.0.0"), as: :turbo_stream

    assert_response :success
    assert_includes response.body, %(target="chat-messages-#{@kase.id}")
  end

  test "chat log with current since returns no content" do
    get fd_case_chat_log_path(@kase, since: Fd::ChatVersion.for(@kase.id)), as: :turbo_stream
    assert_response :no_content
  end

  test "chat log after outbox row is sent returns success" do
    conversation = create_reporter_conversation
    row = Fd::IntakeOutbox.create!(conversation_id: conversation.id, kind: "reply",
      body: "hold on", mode: "signed", requested_by: "UME")
    before = Fd::ChatVersion.for(@kase.id)
    row.update!(sent_at: Time.current)

    get fd_case_chat_log_path(@kase, since: before), as: :turbo_stream

    assert_response :success
  end

  test "chat log with unparseable since returns success" do
    get fd_case_chat_log_path(@kase, since: "garbage"), as: :turbo_stream

    assert_response :success
  end

  def rich(elements)
    [{ "type" => "rich_text",
       "elements" => [{ "type" => "rich_text_section", "elements" => elements }] }]
  end

  test "chat log renders slack line from blocks and not from body" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "_was_ it",
      source_app: "nemo", channel_id: "CLOG", ts: "1.1",
      blocks: rich([{ "type" => "text", "text" => "was", "style" => { "italic" => true } },
                    { "type" => "text", "text" => " it" }]))

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_includes response.body, "<em>was</em>"
    assert_not_includes response.body, "_was_ it"
  end

  test "chat log renders user block as member mention link" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "<@UTHEM> look",
      source_app: "nemo", channel_id: "CLOG", ts: "1.2",
      blocks: rich([{ "type" => "user", "user_id" => "UTHEM" }]))

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_select "a.mention[href=?]", fd_member_path("UTHEM")
  end

  test "chat log renders line without blocks from body text" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "typed here",
      source_app: "fire_engine")

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_includes response.body, "typed here"
  end

  test "chat log renders body without blocks as mrkdwn" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME",
      body: "*look* at <@UTHEM>", source_app: "fire_engine")

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_includes response.body, "<strong>look</strong>"
    assert_select "a.mention[href=?]", fd_member_path("UTHEM")
  end

  def stub_emoji(urls)
    original_for = Slack::Emoji.method(:for)
    Slack::Emoji.define_singleton_method(:for) { |names| urls.slice(*Array(names)) }
    yield
  ensure
    Slack::Emoji.define_singleton_method(:for, original_for)
  end

  test "chat log renders emoji block as custom emoji image" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: ":sho:",
      source_app: "nemo", channel_id: "CLOG", ts: "1.3",
      blocks: rich([{ "type" => "emoji", "name" => "sho" }]))

    stub_emoji({ "sho" => "https://emoji.test/sho.png" }) do
      get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)
    end

    assert_select "img.richtext-emoji-img[src=?]", "https://emoji.test/sho.png"
  end

  test "chat log renders custom emoji in fire_engine body as image" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "nice :sho:",
      source_app: "fire_engine")

    stub_emoji({ "sho" => "https://emoji.test/sho.png" }) do
      get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)
    end

    assert_select "img.richtext-emoji-img[src=?]", "https://emoji.test/sho.png"
  end

  test "chat log renders unknown emoji as its name" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "nice :nope:",
      source_app: "fire_engine")

    stub_emoji({}) do
      get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)
    end

    assert_select "span.richtext-emoji", ":nope:"
  end

  def private_unnamed_channel!(channel_id)
    as_pipeline(<<~SQL.squish,
      INSERT INTO raw.channel_dim (channel_id, name, visibility)
      VALUES (?, NULL, 'private')
      ON CONFLICT (channel_id) DO UPDATE SET name = NULL, visibility = 'private'
    SQL
      channel_id)
    seeded!("raw.channel_dim", "channel_id", channel_id)
  end

  test "chat log renders private channel block as #private-channel without link" do
    private_unnamed_channel!("C0SECRET00")
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "look in it",
      source_app: "nemo", channel_id: "CLOG", ts: "1.4",
      blocks: rich([{ "type" => "channel", "channel_id" => "C0SECRET00" }]))

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_select "span.mention-private", "#private-channel"
    assert_select "a[href*='C0SECRET00']", count: 0
  end

  test "chat log collapses header for same author message one minute later" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "first",
      source_app: "fire_engine", posted_at: 1.hour.ago)
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "second",
      source_app: "fire_engine", posted_at: 1.hour.ago + 1.minute)

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_select ".msg.is-grouped", 1
    assert_select ".msg:not(.is-grouped) .msg-who", text: "@UME"
    assert_select ".msg.is-grouped .msg-who", false
  end

  test "chat log keeps header for same author message one hour later" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "first",
      source_app: "fire_engine", posted_at: 2.hours.ago)
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "second",
      source_app: "fire_engine", posted_at: 1.hour.ago)

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_select ".msg.is-grouped", 0
  end

  test "case show links identified reporter name to member page" do
    Fd::CaseReport.create!(case_id: @kase.id, is_anonymous: false, reporter_user_id: "UREPORTER",
      body: "it happened again", received_at: Time.current, source_app: "relay")

    get fd_case_path(@kase)

    assert_select ".chat-head a.lnk[href=?][data-turbo-frame=?]",
      fd_member_path("UREPORTER"), "person-drawer"
  end

  test "case show renders anonymous reporter name without link" do
    Fd::CaseReport.create!(case_id: @kase.id, is_anonymous: true,
      body: "it happened again", received_at: Time.current, source_app: "relay")

    get fd_case_path(@kase)

    assert_select ".chat-head b", text: "Anonymous"
    assert_select ".chat-head a.lnk", false
  end

  test "chat log after line destroy returns reset content" do
    line = Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "oops",
      source_app: "fire_engine")
    before = Fd::ChatVersion.for(@kase.id)
    line.destroy!

    get fd_case_chat_log_path(@kase, since: before), as: :turbo_stream
    assert_response :reset_content
  end

  test "chats create stores one CaseChat and no note" do
    post fd_case_chats_path(@kase), params: { body: "who wants this one?" },
      as: :turbo_stream

    chat = Fd::CaseChat.where(case_id: @kase.id).sole
    assert_equal "who wants this one?", chat.body
    assert_equal "UME", chat.author_user_id
    assert_nil chat.ts, "ts is nil for a line without a Slack message"
    assert_equal 0, Fd::Note.where(case_id: @kase.id).count
  end

  test "chats create as html redirects to case report tab" do
    post fd_case_chats_path(@kase), params: { body: "who wants this one?" }

    assert_redirected_to fd_case_path(@kase, tab: "report")
  end

  test "chats create with blank body creates no row and flashes alert" do
    post fd_case_chats_path(@kase), params: { body: "  " }

    assert_equal 0, Fd::CaseChat.where(case_id: @kase.id).count
    assert_match(/Enter a message/, flash[:alert])
  end

  test "replies create without reporter creates no outbox row and flashes alert" do
    post fd_case_replies_path(@kase), params: { body: "was this in DMs?" }

    assert_equal 0, Fd::IntakeOutbox.count
    assert_match(/No reporter to reply to/, flash[:alert])
  end

  def create_reporter_conversation
    reporter = Fd::Member.first.user_id
    report = Fd::CaseReport.create!(case_id: @kase.id, reporter_user_id: reporter,
      is_anonymous: false, body: "look at this", source_app: "relay", received_at: 2.days.ago)
    Fd::IntakeConversation.create!(report_id: report.id, member_user_id: reporter,
      channel_id: "D0REP", thread_ts: "1700.5", opened_at: 2.days.ago)
  end

  test "chats create with ? prefix queues signed outbox row and no chat" do
    create_reporter_conversation
    post fd_case_chats_path(@kase), params: { body: "?we are looking at it" },
      as: :turbo_stream

    assert_equal 0, Fd::CaseChat.where(case_id: @kase.id).count, "no chat line created"
    queued = Fd::IntakeOutbox.sole
    assert_equal "we are looking at it", queued.body
    assert_equal "signed", queued.mode
    assert_equal "UME", queued.requested_by
  end

  test "chats create with ~? prefix queues outbox row with mode body" do
    create_reporter_conversation
    post fd_case_chats_path(@kase), params: { body: "~?we are looking at it" },
      as: :turbo_stream

    assert_equal "body", Fd::IntakeOutbox.sole.mode
  end

  test "chats create with ~ prefix and no ? stores chat body and no outbox row" do
    post fd_case_chats_path(@kase), params: { body: "~hi team" }, as: :turbo_stream

    assert_equal "~hi team", Fd::CaseChat.where(case_id: @kase.id).sole.body
    assert_equal 0, Fd::IntakeOutbox.count
  end

  test "replies create signs by default and anon param sets mode body" do
    create_reporter_conversation
    post fd_case_replies_path(@kase), params: { body: "we are on it" }, as: :turbo_stream
    assert_equal "signed", Fd::IntakeOutbox.sole.mode

    post fd_case_replies_path(@kase), params: { body: "and again", anon: "1" },
      as: :turbo_stream
    assert_equal "body", Fd::IntakeOutbox.order(:id).last.mode
  end

  test "chats create with ? prefix without case.reply creates no outbox row or chat" do
    create_reporter_conversation
    restricted_staff = Account.create!(user_id: "UHAND")
    grant_role!("UHAND", "firefighter")
    override_capability!("firefighter", "case.reply", false, by: @me.user_id)
    sign_in_as(restricted_staff)

    post fd_case_chats_path(@kase), params: { body: "?we are looking at it" }

    assert_equal 0, Fd::IntakeOutbox.count
    assert_equal 0, Fd::CaseChat.where(case_id: @kase.id).count, "no chat line created"
    assert_not_nil flash[:alert]
  end

  def stub_chat(name, result)
    original = Slack::Chat.method(name)
    Slack::Chat.define_singleton_method(name) do |*args, **kwargs|
      result.respond_to?(:call) ? result.call(*args, **kwargs) : result
    end
    yield
  ensure
    Slack::Chat.define_singleton_method(name, original)
  end

  def use_firehouse(channel_id = "C0FIRE")
    Fd::AppSetting.set_firehouse_channel(channel_id, by: "UME")
  end

  def link_slack
    Fd::StaffSlack.store!("UME", token: "xoxp-real", team_id: "T0FIRE", scopes: "chat:write")
  end

  def forward_report(card_channel_id: nil)
    Fd::CaseReport.create!(case_id: @kase.id, is_anonymous: true, source_app: "relay",
      received_at: 2.days.ago, forwarded_ts: "1700.0001", card_channel_id: card_channel_id)
  end

  def setup_linked_slack
    use_firehouse
    forward_report
    link_slack
  end

  def post_chat(body = "did we warn them before?")
    post fd_case_chats_path(@kase), params: { body: body }, as: :turbo_stream
    Fd::CaseChat.where(case_id: @kase.id).last
  end

  def recording_posts(sent)
    lambda do |**args|
      sent << args
      { "ok" => true, "ts" => "1700.00#{sent.size}9" }
    end
  end

  test "post_to_thread with linked slack mirrors chat as user with staff token" do
    setup_linked_slack
    sent = nil
    ok_reply = lambda do |**args|
      sent = args
      { "ok" => true, "ts" => "1700.0009" }
    end

    chat = stub_chat(:post_message, ok_reply) { post_chat }

    assert_equal "1700.0009", chat.mirrored_ts
    assert_equal "user", chat.mirrored_as
    assert_not_nil chat.mirrored_at
    assert_equal "C0FIRE", sent[:channel]
    assert_equal "1700.0001", sent[:thread_ts], "thread_ts is the forwarded report ts"
    assert_equal "xoxp-real", sent[:token]
    assert_equal "did we warn them before?", sent[:text]
    assert_not_nil Fd::StaffSlack.active_for("UME").last_used_at
  end

  test "post_to_thread with report card_channel_id posts in that channel" do
    use_firehouse
    forward_report(card_channel_id: "G01DBHPLK25")
    link_slack
    sent = []

    stub_chat(:post_message, recording_posts(sent)) { post_chat }

    assert_equal [["G01DBHPLK25", "1700.0001"]], sent.map { |args| args.values_at(:channel, :thread_ts) }
  end

  test "post_to_thread reads firehouse_channel for each message" do
    setup_linked_slack
    sent = []

    stub_chat(:post_message, recording_posts(sent)) do
      post_chat
      use_firehouse("C0NEWFIRE")
      post_chat("and now?")
    end

    assert_equal %w[C0FIRE C0NEWFIRE], sent.map { |args| args[:channel] }
  end

  test "post_to_thread without reports posts under card_thread_ts" do
    use_firehouse
    link_slack
    @kase.update!(card_channel_id: "C0REACT", card_ts: "1800.0002", card_thread_ts: "1800.0001")
    sent = []

    chat = stub_chat(:post_message, recording_posts(sent)) { post_chat }

    assert_equal "user", chat.mirrored_as
    assert_equal [["C0REACT", "1800.0001"]], sent.map { |args| args.values_at(:channel, :thread_ts) }
  end

  test "post_to_thread without card_thread_ts posts under card_ts" do
    use_firehouse
    link_slack
    @kase.update!(card_channel_id: "C0FIRE", card_ts: "1800.0002")
    sent = []

    stub_chat(:post_message, recording_posts(sent)) { post_chat }

    assert_equal [["C0FIRE", "1800.0002"]], sent.map { |args| args.values_at(:channel, :thread_ts) }
  end

  test "post_to_thread with not_in_channel error leaves mirrored_ts nil and stores last_error" do
    setup_linked_slack
    refusal = ->(**) { { "ok" => false, "error" => "not_in_channel" } }

    chat = stub_chat(:post_message, refusal) { post_chat }

    assert_nil chat.mirrored_ts, "mirrored_ts is nil after refusal"
    assert_nil chat.mirrored_as
    assert_equal "not_in_channel", Fd::StaffSlack.active_for("UME").last_error
  end

  test "post_to_thread with token_revoked error marks staff slack revoked" do
    setup_linked_slack
    revoked_reply = ->(**) { { "ok" => false, "error" => "token_revoked" } }

    chat = stub_chat(:post_message, revoked_reply) { post_chat }

    assert_nil chat.mirrored_as
    assert_nil Fd::StaffSlack.active_for("UME"), "revoked staff slack is not active"
    row = Fd::StaffSlack.find_by(staff_user_id: "UME")
    assert row.revoked_by_slack?
    assert_equal "token_revoked", row.last_error
  end

  test "post_to_thread with UnavailableError leaves mirrored_as nil and stores last_error" do
    setup_linked_slack
    unavailable_reply = ->(**) { raise Slack::Chat::UnavailableError, "execution expired" }

    chat = stub_chat(:post_message, unavailable_reply) { post_chat }

    assert_nil chat.mirrored_as
    assert_match(/execution expired/, Fd::StaffSlack.active_for("UME").last_error)
  end

  test "post_to_thread without linked slack sends nothing and leaves mirrored_as nil" do
    use_firehouse
    forward_report

    chat = stub_chat(:post_message, ->(**) { flunk "nothing should be sent" }) { post_chat }

    assert_nil chat.mirrored_as
    assert_nil chat.mirrored_ts
  end

  test "post_to_thread without report or card thread sends nothing" do
    use_firehouse
    link_slack

    chat = stub_chat(:post_message, ->(**) { flunk "there is no thread to post into" }) { post_chat }

    assert_nil chat.mirrored_as
  end

  test "claimable? without firehouse_channel or card_channel_id is false" do
    forward_report
    link_slack

    chat = stub_chat(:post_message, ->(**) { flunk "there is no channel to post into" }) { post_chat }

    assert_nil chat.mirrored_as
  end

  test "Fd::SlackPost.escape_markup keeps mentions and escapes markup characters" do
    assert_equal "&lt;b&gt; <@U0A1> &amp; me",
      Fd::SlackPost.escape_markup("<b> <@U0A1> & me")
  end

  test "chat log renders action blocks as action card without reporter tag" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", source_app: "fire_engine",
      blocks: [
        { "type" => "header", "text" => { "type" => "plain_text", "text" => "Warning" } },
        { "type" => "context",
          "elements" => [{ "type" => "mrkdwn", "text" => "Against <@UTHEM> · logged by <@UME>" }] },
        { "type" => "section", "text" => { "type" => "mrkdwn", "text" => "> kept at it" } }
      ])

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_includes response.body, %(data-kind="action")
    assert_includes response.body, %(class="echo-head">Warning</p>)
    assert_not_includes response.body, "tag-reporter"
  end

  test "chat log of an imported case without its chat shows not imported yet" do
    kase = make_case(source_app: "lyla")

    get fd_case_chat_log_path(kase)

    assert_select ".empty-title", "Not imported yet"
  end

  test "chat log of an imported case with its chat shows the usual empty state" do
    kase = make_case(source_app: "lyla", chat_imported_at: Time.current)

    get fd_case_chat_log_path(kase)

    assert_select ".empty-title", "No report on file"
  end

  test "chat log of an imported case with messages and no import marks the gap" do
    kase = make_case(source_app: "lyla")
    Fd::CaseChat.create!(case_id: kase.id, author_user_id: "UME", body: "noted", source_app: "fire_engine")

    get fd_case_chat_log_path(kase)

    assert_select "p.dayrule", "Not imported yet"
  end
end

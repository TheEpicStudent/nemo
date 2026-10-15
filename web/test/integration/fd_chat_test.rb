require "test_helper"

class FdChatTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = hold_role!("UME", "community_manager")
    @kase = make_case
    sign_in_as(@me)
  end

  test "a message to the team answers with a stream that reloads the log" do
    post fd_case_chats_path(@kase), params: { body: "who wants this one?" },
      as: :turbo_stream

    assert_response :success
  end

  test "the chat log renders as html, not only as a stream" do
    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_response :success
  end

  test "the scroll container does not share the frame id, so upsert reaches it" do
    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_equal 1, response.body.scan(/id="chat-log-#{@kase.id}"/).size,
      "the frame id must not be reused by the scroll container"
    assert_includes response.body, %(id="chat-messages-#{@kase.id}" class="chatscroll")
  end

  test "the live stream upserts into the scroll container, not the frame" do
    post fd_case_chats_path(@kase), params: { body: "meow" }, as: :turbo_stream
    get fd_case_chat_log_path(@kase, since: "0.0.0"), as: :turbo_stream

    assert_response :success
    assert_includes response.body, %(target="chat-messages-#{@kase.id}")
  end

  test "asked what changed when nothing did, the log says nothing" do
    get fd_case_chat_log_path(@kase, since: Fd::ChatVersion.for(@kase.id)), as: :turbo_stream
    assert_response :no_content
  end

  test "a reply that went out is taken off the log" do
    conversation = create_reporter_conversation
    row = Fd::IntakeOutbox.create!(conversation_id: conversation.id, kind: "reply",
      body: "hold on", mode: "signed", requested_by: "UME")
    before = Fd::ChatVersion.for(@kase.id)
    row.update!(sent_at: Time.current)

    get fd_case_chat_log_path(@kase, since: before), as: :turbo_stream

    assert_response :success
  end

  test "a since it cannot read gets the whole log as one upsert" do
    get fd_case_chat_log_path(@kase, since: "garbage"), as: :turbo_stream

    assert_response :success
  end

  def rich(elements)
    [{ "type" => "rich_text",
       "elements" => [{ "type" => "rich_text_section", "elements" => elements }] }]
  end

  test "a line that came from slack is drawn from its blocks" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "_was_ it",
      source_app: "nemo", channel_id: "CLOG", ts: "1.1",
      blocks: rich([{ "type" => "text", "text" => "was", "style" => { "italic" => true } },
                    { "type" => "text", "text" => " it" }]))

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_includes response.body, "<em>was</em>"
    assert_not_includes response.body, "_was_ it"
  end

  test "a mention in a slack line still links to the member" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "<@UTHEM> look",
      source_app: "nemo", channel_id: "CLOG", ts: "1.2",
      blocks: rich([{ "type" => "user", "user_id" => "UTHEM" }]))

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_select "a.mention[href=?]", fd_member_path("UTHEM")
  end

  test "a line with no blocks is still drawn from its text" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "typed here",
      source_app: "fire_engine")

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_includes response.body, "typed here"
  end

  test "a line with no blocks is read as mrkdwn" do
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

  test "a custom emoji in a slack line becomes its image" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: ":sho:",
      source_app: "nemo", channel_id: "CLOG", ts: "1.3",
      blocks: rich([{ "type" => "emoji", "name" => "sho" }]))

    stub_emoji({ "sho" => "https://emoji.test/sho.png" }) do
      get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)
    end

    assert_select "img.richtext-emoji-img[src=?]", "https://emoji.test/sho.png"
  end

  test "a custom emoji typed in the fire engine is looked up too" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "nice :sho:",
      source_app: "fire_engine")

    stub_emoji({ "sho" => "https://emoji.test/sho.png" }) do
      get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)
    end

    assert_select "img.richtext-emoji-img[src=?]", "https://emoji.test/sho.png"
  end

  test "an emoji nobody knows stays as its name" do
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

  test "a private channel mentioned in a slack line never shows its real name" do
    private_unnamed_channel!("C0SECRET00")
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "look in it",
      source_app: "nemo", channel_id: "CLOG", ts: "1.4",
      blocks: rich([{ "type" => "channel", "channel_id" => "C0SECRET00" }]))

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_select "span.mention-private", "#private-channel"
    assert_select "a[href*='C0SECRET00']", count: 0
  end

  test "two messages from the same author close together collapse the header" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "first",
      source_app: "fire_engine", posted_at: 1.hour.ago)
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "second",
      source_app: "fire_engine", posted_at: 1.hour.ago + 1.minute)

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_select ".msg.is-grouped", 1
    assert_select ".msg:not(.is-grouped) .msg-who", text: "@UME"
    assert_select ".msg.is-grouped .msg-who", false
  end

  test "a reply far enough apart keeps its own header" do
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "first",
      source_app: "fire_engine", posted_at: 2.hours.ago)
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "second",
      source_app: "fire_engine", posted_at: 1.hour.ago)

    get fd_case_chat_log_path(@kase, thread: @kase.reports.first&.id)

    assert_select ".msg.is-grouped", 0
  end

  test "an identified reporter's name links to their member page" do
    Fd::CaseReport.create!(case_id: @kase.id, is_anonymous: false, reporter_user_id: "UREPORTER",
      body: "it happened again", received_at: Time.current, source_app: "relay")

    get fd_case_path(@kase)

    assert_select ".chat-head a.lnk[href=?][data-turbo-frame=?]",
      fd_member_path("UREPORTER"), "person-drawer"
  end

  test "an anonymous reporter's name is not a link" do
    Fd::CaseReport.create!(case_id: @kase.id, is_anonymous: true,
      body: "it happened again", received_at: Time.current, source_app: "relay")

    get fd_case_path(@kase)

    assert_select ".chat-head b", text: "Anonymous"
    assert_select ".chat-head a.lnk", false
  end

  test "a deletion sends the browser back for a full reload" do
    line = Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: "oops",
      source_app: "fire_engine")
    before = Fd::ChatVersion.for(@kase.id)
    line.destroy!

    get fd_case_chat_log_path(@kase, since: before), as: :turbo_stream
    assert_response :reset_content
  end

  test "the message is kept as working chat, not as a note" do
    post fd_case_chats_path(@kase), params: { body: "who wants this one?" },
      as: :turbo_stream

    chat = Fd::CaseChat.where(case_id: @kase.id).sole
    assert_equal "who wants this one?", chat.body
    assert_equal "UME", chat.author_user_id
    assert_nil chat.ts, "typed here, so it has not been to Slack yet"
    assert_equal 0, Fd::Note.where(case_id: @kase.id).count
  end

  test "a plain browser still gets a redirect" do
    post fd_case_chats_path(@kase), params: { body: "who wants this one?" }

    assert_redirected_to fd_case_path(@kase, tab: "report")
  end

  test "an empty message is refused" do
    post fd_case_chats_path(@kase), params: { body: "  " }

    assert_equal 0, Fd::CaseChat.where(case_id: @kase.id).count
    assert_match(/write something/, flash[:alert])
  end

  test "a reply with nobody to reply to says so" do
    post fd_case_replies_path(@kase), params: { body: "was this in DMs?" }

    assert_equal 0, Fd::IntakeOutbox.count
    assert_match(/nobody to reply to/, flash[:alert])
  end

  def create_reporter_conversation
    reporter = Fd::Member.first.user_id
    report = Fd::CaseReport.create!(case_id: @kase.id, reporter_user_id: reporter,
      is_anonymous: false, body: "look at this", source_app: "relay", received_at: 2.days.ago)
    Fd::IntakeConversation.create!(report_id: report.id, member_user_id: reporter,
      channel_id: "D0REP", thread_ts: "1700.5", opened_at: 2.days.ago)
  end

  test "a marked message typed at the team endpoint goes to the reporter, signed" do
    create_reporter_conversation
    post fd_case_chats_path(@kase), params: { body: "?we are looking at it" },
      as: :turbo_stream

    assert_equal 0, Fd::CaseChat.where(case_id: @kase.id).count, "it left the room"
    queued = Fd::IntakeOutbox.sole
    assert_equal "we are looking at it", queued.body
    assert_equal "signed", queued.mode
    assert_equal "UME", queued.requested_by
  end

  test "the tilde takes your name off a reply typed at the team endpoint" do
    create_reporter_conversation
    post fd_case_chats_path(@kase), params: { body: "~?we are looking at it" },
      as: :turbo_stream

    assert_equal "body", Fd::IntakeOutbox.sole.mode
  end

  test "a tilde on its own is kept as words, not read as a mark" do
    post fd_case_chats_path(@kase), params: { body: "~hi team" }, as: :turbo_stream

    assert_equal "~hi team", Fd::CaseChat.where(case_id: @kase.id).sole.body
    assert_equal 0, Fd::IntakeOutbox.count
  end

  test "the reply endpoint signs by default and takes the anon flag" do
    create_reporter_conversation
    post fd_case_replies_path(@kase), params: { body: "we are on it" }, as: :turbo_stream
    assert_equal "signed", Fd::IntakeOutbox.sole.mode

    post fd_case_replies_path(@kase), params: { body: "and again", anon: "1" },
      as: :turbo_stream
    assert_equal "body", Fd::IntakeOutbox.order(:id).last.mode
  end

  test "somebody who may not reply cannot get there through the team endpoint" do
    create_reporter_conversation
    restricted_staff = Account.create!(user_id: "UHAND")
    hold_role!("UHAND", "firefighter")
    move_capability!("firefighter", "case.reply", false, by: @me.user_id)
    sign_in_as(restricted_staff)

    post fd_case_chats_path(@kase), params: { body: "?we are looking at it" }

    assert_equal 0, Fd::IntakeOutbox.count
    assert_equal 0, Fd::CaseChat.where(case_id: @kase.id).count, "and it is not filed as chat"
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

  test "with slack linked, the message goes out as you and the bot leaves it alone" do
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
    assert_equal "1700.0001", sent[:thread_ts], "it lands in the case thread, not the channel"
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

  test "slack refusing it hands the message back to the bot and says why" do
    setup_linked_slack
    refusal = ->(**) { { "ok" => false, "error" => "not_in_channel" } }

    chat = stub_chat(:post_message, refusal) { post_chat }

    assert_nil chat.mirrored_ts, "nothing was sent, so nemo still has to carry it"
    assert_nil chat.mirrored_as
    assert_equal "not_in_channel", Fd::StaffSlack.active_for("UME").last_error
  end

  test "a dead token is given up on, not tried again for every message" do
    setup_linked_slack
    revoked_reply = ->(**) { { "ok" => false, "error" => "token_revoked" } }

    chat = stub_chat(:post_message, revoked_reply) { post_chat }

    assert_nil chat.mirrored_as
    assert_nil Fd::StaffSlack.active_for("UME"), "it stops claiming messages it cannot send"
    row = Fd::StaffSlack.find_by(staff_user_id: "UME")
    assert row.revoked_by_slack?
    assert_equal "token_revoked", row.last_error
  end

  test "slack being unreachable hands the message back to the bot" do
    setup_linked_slack
    unavailable_reply = ->(**) { raise Slack::Chat::UnavailableError, "execution expired" }

    chat = stub_chat(:post_message, unavailable_reply) { post_chat }

    assert_nil chat.mirrored_as
    assert_match(/execution expired/, Fd::StaffSlack.active_for("UME").last_error)
  end

  test "without slack linked, the message is left for the bot untouched" do
    use_firehouse
    forward_report

    chat = stub_chat(:post_message, ->(**) { flunk "nothing should be sent" }) { post_chat }

    assert_nil chat.mirrored_as
    assert_nil chat.mirrored_ts
  end

  test "a case with no card in the firehouse is left for the bot" do
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

  test "a mention survives, the rest is escaped for slack" do
    assert_equal "&lt;b&gt; <@U0A1> &amp; me",
      Fd::SlackPost.escape_markup("<b> <@U0A1> & me")
  end

  test "a logged action renders as its own highlighted card, not a reporter reply" do
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
end

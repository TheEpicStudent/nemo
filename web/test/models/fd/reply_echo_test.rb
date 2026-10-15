require "test_helper"

class Fd::ReplyEchoTest < ActiveSupport::TestCase
  setup do
    @kase = make_case
    reporter = Fd::Member.first.user_id
    @report = Fd::CaseReport.create!(case_id: @kase.id, reporter_user_id: reporter,
      is_anonymous: false, body: "look at this", source_app: "relay",
      received_at: 2.days.ago, forwarded_ts: "1700.0001")
    @conversation = Fd::IntakeConversation.create!(report_id: @report.id,
      member_user_id: reporter, channel_id: "D0REP", thread_ts: "1700.5",
      opened_at: 2.days.ago)
    use_firehouse
  end

  def use_firehouse(channel_id = "C0FIRE")
    Fd::AppSetting.set_firehouse_channel(channel_id, by: "UME")
  end

  def recording_posts(sent)
    lambda do |**args|
      sent << args
      { "ok" => true, "ts" => "1700.01#{sent.size}" }
    end
  end

  def stub_post_message(result)
    original = Slack::Chat.method(:post_message)
    Slack::Chat.define_singleton_method(:post_message) do |*args, **kwargs|
      result.respond_to?(:call) ? result.call(*args, **kwargs) : result
    end
    yield
  ensure
    Slack::Chat.define_singleton_method(:post_message, original)
  end

  def queue(mode: "signed", by: "UME", sent: true)
    Fd::IntakeOutbox.create!(conversation_id: @conversation.id, kind: "reply",
      body: "we are looking at it", mode: mode, requested_by: by,
      sent_at: (Time.current if sent))
  end

  def link(user_id = "UME")
    Fd::StaffSlack.store!(user_id, token: "xoxp-real", team_id: "T0FIRE", scopes: "chat:write")
  end

  test "a sent reply from a linked author is echoed with their own token" do
    link
    queued = queue
    sent = nil

    echoed_count = stub_post_message(lambda { |**args|
      sent = args
      { "ok" => true, "ts" => "1700.0100" }
    }) { Fd::ReplyEcho.flush_pending(@kase.id) }

    assert_equal 1, echoed_count
    assert_equal "xoxp-real", sent[:token]
    assert_equal "C0FIRE", sent[:channel]
    assert_equal "1700.0001", sent[:thread_ts]
    assert_equal "?we are looking at it", sent[:text]
    assert_equal "1700.0100", queued.reload.echoed_ts
    assert_equal "user", queued.echoed_as
  end

  test "an anonymous reply carries both marks so the thread can see which it was" do
    link
    queue(mode: "body")
    sent = nil

    stub_post_message(lambda { |**args|
      sent = args
      { "ok" => true, "ts" => "1700.0101" }
    }) { Fd::ReplyEcho.flush_pending(@kase.id) }

    assert_equal "~?we are looking at it", sent[:text]
  end

  test "an author who never linked is left for the bot" do
    queued = queue

    echoed_count = stub_post_message(->(**) { flunk "the bot echoes this one" }) {
      Fd::ReplyEcho.flush_pending(@kase.id)
    }

    assert_equal 0, echoed_count
    assert_nil queued.reload.echoed_at
  end

  test "a reply that has not gone yet is not echoed" do
    link
    queued = queue(sent: false)

    stub_post_message(->(**) { flunk "nothing has been sent to the reporter yet" }) {
      Fd::ReplyEcho.flush_pending(@kase.id)
    }

    assert_nil queued.reload.echoed_at
  end

  test "the claim means two notifications only echo once" do
    link
    queued = queue
    tries = 0

    stub_post_message(lambda { |**|
      tries += 1
      { "ok" => true, "ts" => "1700.0102" }
    }) do
      Fd::ReplyEcho.flush_pending(@kase.id)
      Fd::ReplyEcho.flush_pending(@kase.id)
    end

    assert_equal 1, tries
    assert_equal "1700.0102", queued.reload.echoed_ts
  end

  test "slack refusing it lets the claim go and says why" do
    grant = link
    queued = queue

    stub_post_message(->(**) { { "ok" => false, "error" => "not_in_channel" } }) do
      Fd::ReplyEcho.flush_pending(@kase.id)
    end

    assert_nil queued.reload.echoed_at, "it can be tried again"
    assert_equal "not_in_channel", grant.reload.last_error
  end

  def with_a_failing_write
    Fd::IntakeOutbox.class_eval do
      alias_method :real_update!, :update!
      define_method(:update!) { |*| raise ActiveRecord::StatementInvalid, "connection lost" }
    end
    yield
  ensure
    Fd::IntakeOutbox.class_eval do
      remove_method :update!
      alias_method :update!, :real_update!
      remove_method :real_update!
    end
  end

  test "a write that fails after the post lets the claim go and raises to be retried" do
    grant = link
    queued = queue

    with_a_failing_write do
      stub_post_message(->(**) { { "ok" => true, "ts" => "1700.0103" } }) do
        assert_raises(ActiveRecord::StatementInvalid) { Fd::ReplyEcho.flush_pending(@kase.id) }
      end
    end

    assert_nil queued.reload.echoed_at, "the claim is released so the job can retry"
    assert_nil queued.echoed_ts
    assert_nil grant.reload.last_error, "a database failure is not the grant's fault"
  end

  test "a case with no card in the firehouse echoes nothing" do
    link
    @report.update!(forwarded_ts: nil)
    queued = queue

    stub_post_message(->(**) { flunk "there is no thread to echo into" }) do
      Fd::ReplyEcho.flush_pending(@kase.id)
    end

    assert_nil queued.reload.echoed_at
  end

  test "flush_pending posts in report card_channel_id" do
    link
    @report.update!(card_channel_id: "G01DBHPLK25")
    queue
    sent = []

    stub_post_message(recording_posts(sent)) { Fd::ReplyEcho.flush_pending(@kase.id) }

    assert_equal [["G01DBHPLK25", "1700.0001"]], sent.map { |args| args.values_at(:channel, :thread_ts) }
  end

  test "flush_pending posts each row under its report forwarded_ts" do
    link
    queue
    other_report = Fd::CaseReport.create!(case_id: @kase.id, reporter_user_id: @report.reporter_user_id,
      is_anonymous: false, body: "me too", source_app: "relay", received_at: 1.day.ago,
      forwarded_ts: "1700.0002", card_channel_id: "C07FL3G62LF")
    other_conversation = Fd::IntakeConversation.create!(report_id: other_report.id,
      member_user_id: @report.reporter_user_id, channel_id: "D0REP", thread_ts: "1700.6",
      opened_at: 1.day.ago)
    Fd::IntakeOutbox.create!(conversation_id: other_conversation.id, kind: "reply",
      body: "thanks for this one too", mode: "signed", requested_by: "UME",
      sent_at: 1.minute.from_now)
    sent = []

    stub_post_message(recording_posts(sent)) { Fd::ReplyEcho.flush_pending(@kase.id) }

    assert_equal [["C0FIRE", "1700.0001"], ["C07FL3G62LF", "1700.0002"]],
      sent.map { |args| args.values_at(:channel, :thread_ts) }
  end

  test "flush_pending reads firehouse_channel for each row" do
    link
    queue
    sent = []

    stub_post_message(recording_posts(sent)) do
      Fd::ReplyEcho.flush_pending(@kase.id)
      use_firehouse("C0NEWFIRE")
      queue
      Fd::ReplyEcho.flush_pending(@kase.id)
    end

    assert_equal %w[C0FIRE C0NEWFIRE], sent.map { |args| args[:channel] }
  end

  test "flush_pending without firehouse_channel or card_channel_id leaves row unclaimed" do
    link
    Fd::AppSetting.where(key: Fd::AppSetting::FIREHOUSE).delete_all
    queued = queue

    stub_post_message(->(**) { flunk "there is no channel to echo into" }) do
      Fd::ReplyEcho.flush_pending(@kase.id)
    end

    assert_nil queued.reload.echoed_at
  end
end

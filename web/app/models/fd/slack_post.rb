module Fd
  class SlackPost
    def self.log_channel_id
      ENV["INTERNAL_LOG_CHANNEL_ID"].presence
    end

    def self.thread_for(case_id)
      CaseReport.where(case_id: case_id).where.not(forwarded_ts: nil)
        .order(:received_at).pick(:forwarded_ts)
    end

    def self.claimable?(case_id, author_user_id)
      return false if log_channel_id.nil?
      return false if StaffSlack.active_for(author_user_id).nil?

      thread_for(case_id).present?
    end

    def self.post_to_thread(chat)
      grant = StaffSlack.active_for(chat.author_user_id)
      thread_ts = thread_for(chat.case_id)
      return mark_unsent(chat, "there is nothing to send it with") if grant.nil? || thread_ts.nil?

      result = post_message(grant, thread_ts, chat.body)
      return mark_unsent(chat, result[:error], grant) unless result[:ts]

      chat.update!(mirrored_ts: result[:ts], mirrored_at: Time.current, mirrored_as: "user")
      grant.used!
      true
    end

    def self.post_message(grant, thread_ts, body)
      response = Slack::Chat.post_message(token: grant.user_token, channel: log_channel_id,
        thread_ts: thread_ts, text: escape_markup(body))
      return { ts: response["ts"] } if response["ok"]

      { error: response["error"].to_s.presence || "slack refused it" }
    rescue Slack::Chat::UnavailableError => error
      { error: error.message }
    end

    def self.mark_unsent(chat, error_message, grant = nil)
      grant&.record_error!(error_message)
      chat.update!(mirrored_as: nil)
      false
    end

    def self.escape_markup(body)
      Mentions.split(body).map { |part|
        part.start_with?("<@") ? part : plain_text(part)
      }.join
    end

    def self.plain_text(part)
      part.gsub("&", "&amp;").gsub("<", "&lt;").gsub(">", "&gt;")
    end
  end
end

module Channels
  class Posts
    POST_LIMIT = 3

    Post = Struct.new(:channel_id, :ts, :author_id, :posted_at, :replies, :reactions, :result,
      keyword_init: true) do
      def error = result&.error
      def message = result&.message
      def files = Messages::File.listed(message)

      def reactions_label
        Array(message && message["reactions"]).select { |reaction| reaction["name"].present? }
      end
    end

    def self.may_read?(viewer, subject_id)
      viewer.present? && subject_id.present? && viewer.user_id == subject_id
    end

    def self.rows(channel_id:, subject_id:, limit: POST_LIMIT)
      Analytics::FctMessage
        .where(channel_id: channel_id, author_id: subject_id, is_reply: false, subtype: nil)
        .order(posted_at: :desc)
        .limit(limit)
        .to_a
    end

    def self.for(channel_id:, subject_id:, limit: POST_LIMIT)
      message_rows = rows(channel_id: channel_id, subject_id: subject_id, limit: limit)
      message_rows.filter_map { |row| post_for(row) }
    end

    def self.post_for(row)
      result = Slack::Message.at(row.channel_id, row.ts)
      return nil if result.error == :not_found

      Post.new(
        channel_id: row.channel_id, ts: row.ts, author_id: row.author_id,
        posted_at: row.posted_at, replies: row.reply_count.to_i,
        reactions: row.reaction_count.to_i, result: result
      )
    end
  end
end

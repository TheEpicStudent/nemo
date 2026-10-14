module Fd
  class ChannelPurge < ApplicationRecord
    self.table_name = "fd.purges"

    PROPOSED = "proposed".freeze
    ASKED = "asked".freeze
    RUNNING = "running".freeze
    CHECKING = "checking".freeze
    DONE = "done".freeze
    FAILED = "failed".freeze

    WAITING = [ASKED, RUNNING, CHECKING].freeze
    MOST = 100

    belongs_to :kase, class_name: "Fd::Case", foreign_key: :case_id, optional: true,
      inverse_of: false
    has_many :items, -> { order(:ts) }, class_name: "Fd::PurgeItem", foreign_key: :purge_id,
      inverse_of: :purge, dependent: nil

    scope :waiting, -> { where(state: WAITING) }
    scope :confirmed, -> { where.not(state: PROPOSED) }
    scope :newest_first, -> { order(asked_at: :desc, id: :desc) }
    scope :for_channel, ->(channel_id) { where(channel_id: channel_id) }

    def self.waiting_on?(channel_id)
      waiting.for_channel(channel_id).exists?
    end

    def waiting? = WAITING.include?(state)
    def done? = state == DONE
    def failed? = state == FAILED

    def transcript_entries
      items.map(&:transcript_entry)
    end

    def reply_count
      transcript_entries.count { |entry| entry["thread_ts"].present? }
    end

    Message = Struct.new(:ts, :thread_ts, :user, :text, keyword_init: true) do
      def at
        Time.zone.at(ts.to_f) if ts.to_s.include?(".")
      end
    end

    class Reading
      def initialize(transcript)
        @messages = transcript.map { |entry| Message.new(**entry.symbolize_keys.slice(*Message.members)) }
      end

      def top_level
        @top_level ||= @messages.reject { |message| message.thread_ts.present? }.sort_by { |message| message.ts.to_f }
      end

      def below(parent)
        replies.fetch(parent.ts, [])
      end

      def orphans
        @orphans ||= replies.reject { |ts, _| top_level.any? { |message| message.ts == ts } }.values.flatten
      end

      def any? = @messages.any?

      private

      def replies
        @replies ||= @messages.select { |message| message.thread_ts.present? }
          .group_by(&:thread_ts)
          .transform_values { |thread_replies| thread_replies.sort_by { |message| message.ts.to_f } }
      end
    end

    def people_named
      [asked_by] + transcript_entries.filter_map { |entry| entry["user"] }
    end
  end
end

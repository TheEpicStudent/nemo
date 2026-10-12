module Engine
  class Archive
    WORKER = "archive_worker".freeze
    ERRORS_LIMIT = 10
    ERROR_WIDTH = 90
    WORST_LIMIT = 12
    WORST_FLOOR = 250
    WAITING_LIMIT = 12
    COVERAGE_DAYS = 90
    QUEUES = %w[channel_tail channel_replies].freeze

    TOTALS_SQL = <<~SQL.freeze
      SELECT count(*)                                                        AS channels,
             count(*) FILTER (WHERE unreachable_reason IS NOT NULL)          AS unreachable,
             count(*) FILTER (WHERE unreachable_reason IS NULL)              AS reachable,
             count(*) FILTER (WHERE walked)                                  AS walked,
             count(*) FILTER (WHERE history_complete
                              AND unreachable_reason IS NULL)               AS complete,
             count(*) FILTER (WHERE unreachable_reason IS NULL AND NOT walked) AS untouched,
             count(*) FILTER (WHERE messages_held > 0
                              AND unreachable_reason IS NULL)               AS holding,
             coalesce(sum(messages_held), 0)                                 AS messages_held,
             coalesce(sum(parents_held), 0)                                  AS parents_held,
             coalesce(sum(replies_held), 0)                                  AS replies_held,
             coalesce(sum(threads_known), 0)                                 AS threads_known,
             coalesce(sum(threads_fetched), 0)                               AS threads_fetched,
             coalesce(sum(replies_declared), 0)                              AS replies_declared,
             coalesce(sum(slack_messages), 0)                                AS slack_messages,
             min(oldest_held)                                                AS oldest_held,
             max(newest_held)                                                AS newest_held,
             max(last_walked_at)                                             AS last_walked_at
      FROM   analytics.mart_archive_channel_coverage
    SQL

    Totals = Struct.new(:row) do
      %w[channels unreachable reachable walked complete untouched holding messages_held
         parents_held replies_held threads_known threads_fetched replies_declared
         slack_messages].each do |name|
        define_method(name) { row[name].to_i }
      end

      def oldest_archived = row["oldest_held"]&.to_time
      def newest_archived = row["newest_held"]&.to_time
      def last_walked_at = row["last_walked_at"]&.to_time

      def archived_days
        return nil if oldest_archived.nil? || newest_archived.nil?

        (newest_archived.to_date - oldest_archived.to_date).to_i + 1
      end

      def threads_waiting = [threads_known - threads_fetched, 0].max

      def replies_waiting = [replies_declared - replies_held, 0].max
    end

    Stage = Struct.new(:name, :done, :total, :at, keyword_init: true) do
      def outstanding
        return nil if total.nil?

        [total - done, 0].max
      end

      def share
        return nil if total.nil? || total.zero?

        done.to_f / total * 100
      end

      def visible_share
        return nil if share.nil?
        return [share, 99.9].min if outstanding.positive?

        [share, 100.0].min
      end
    end

    Report = Struct.new(:totals, :live, :stages, :worst, :waiting, :errors, :beat, :days,
      :queues, keyword_init: true)

    def self.report
      totals = Totals.new(ApplicationRecord.connection.select_one(TOTALS_SQL))
      Report.new(totals: totals, live: live(totals), stages: stages(totals), worst: worst,
        waiting: waiting, errors: errors, beat: beat, days: days, queues: queues)
    end

    WATERMARK_SQL = "SELECT max(observed_through) FROM analytics.fct_message_hour".freeze

    MESSAGES_SINCE_SQL = <<~SQL.freeze
      SELECT count(*)                         AS messages,
             count(*) FILTER (WHERE is_reply) AS replies
      FROM   analytics.fct_archive_landing
      WHERE  deleted_at IS NULL AND first_seen_at > :since
    SQL

    Live = Struct.new(:messages_archived, :parents_archived, :replies_archived, :messages_since,
      keyword_init: true)

    def self.live(totals)
      return nil unless Analytics::FctArchiveLanding.table_exists?

      watermark = ApplicationRecord.connection.select_value(WATERMARK_SQL)
      return nil if watermark.nil?

      row = ApplicationRecord.connection.select_one(
        ApplicationRecord.sanitize_sql([MESSAGES_SINCE_SQL, since: watermark])
      )
      messages_since = row["messages"].to_i
      replies = totals.replies_held + row["replies"].to_i
      Live.new(messages_archived: totals.messages_held + messages_since, replies_archived: replies,
        parents_archived: totals.messages_held + messages_since - replies, messages_since: messages_since)
    end

    def self.stages(totals)
      [
        Stage.new(name: "channels walked", done: totals.complete, total: totals.reachable,
                  at: totals.last_walked_at),
        Stage.new(name: "threads fetched", done: totals.threads_fetched,
                  total: totals.threads_known, at: nil),
        Stage.new(name: "replies held", done: totals.replies_held,
                  total: totals.replies_declared, at: nil)
      ]
    end

    def self.worst
      return Analytics::MartArchiveChannelCoverage.none unless ranks_by_member?

      Analytics::MartArchiveChannelCoverage
        .reachable
        .where("slack_member_messages >= ?", WORST_FLOOR)
        .where("member_share is not null")
        .order(member_share: :asc, slack_member_messages: :desc)
        .limit(WORST_LIMIT)
    end

    def self.ranks_by_member?
      Analytics::MartArchiveChannelCoverage.column_names.include?("member_share")
    end

    def self.waiting
      Analytics::MartArchiveChannelCoverage
        .reachable
        .where("not history_complete")
        .order(Arel.sql("walked, threads_known - threads_fetched desc, messages_held desc"))
        .limit(WAITING_LIMIT)
    end

    def self.errors
      Analytics::FctChannelWalk.failed
        .group(Arel.sql("left(last_error, #{ERROR_WIDTH})"))
        .order(Arel.sql("count(*) desc"))
        .limit(ERRORS_LIMIT)
        .pluck(Arel.sql("left(last_error, #{ERROR_WIDTH})"), Arel.sql("count(*)"),
          Arel.sql("max(last_walked_at)"))
    end

    def self.beat
      Analytics::FctWorkerHeartbeat.find_by(worker: WORKER)
    end

    def self.days
      Analytics::MartArchiveDayCoverage.newest_first.limit(COVERAGE_DAYS).to_a.reverse
    end

    def self.queues
      Analytics::FctWorkQueue.where(work_kind: QUEUES).order(:work_kind).to_a
    end
  end
end

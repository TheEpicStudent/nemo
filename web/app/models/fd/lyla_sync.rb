module Fd
  class LylaSync
    READER = "reader".freeze
    WRITER = "writer".freeze
    IMPORT = "import".freeze
    FIREHOSE = "firehose".freeze

    Status = Struct.new(:imported_at, :import_running, :import_error, :read_at, :read_error, :written_at,
      :write_error, :firehose_at, :firehose_error, :waiting, :failed, :conflicts, :chat_waiting,
      keyword_init: true)

    STATUS_SQL = <<~SQL.freeze
      SELECT name, ok_at, error, ran_at FROM fd.lyla_sync_status
    SQL

    OUTBOX_SQL = <<~SQL.freeze
      SELECT count(*) FILTER (WHERE applied_at IS NULL),
             count(*) FILTER (WHERE applied_at IS NULL AND error IS NOT NULL),
             count(*) FILTER (WHERE conflict IS NOT NULL AND queued_at > now() - interval '1 day')
      FROM fd.lyla_outbox
    SQL

    CHAT_WAITING_SQL = <<~SQL.freeze
      SELECT count(*) FROM fd.cases WHERE source_app = 'lyla' AND chat_imported_at IS NULL
    SQL

    def self.status
      connection = ApplicationRecord.connection
      runs = connection.select_rows(STATUS_SQL).to_h { |name, *values| [name, values] }
      waiting, failed, conflicts = connection.select_rows(OUTBOX_SQL).first
      import_ok, import_error, import_ran = runs[IMPORT]
      Status.new(
        imported_at: time(import_ok), import_error: import_error,
        import_running: import_ran.present? && import_ok.nil? && import_error.nil?,
        read_at: time(runs.dig(READER, 0)), read_error: runs.dig(READER, 1),
        written_at: time(runs.dig(WRITER, 0)), write_error: runs.dig(WRITER, 1),
        firehose_at: time(runs.dig(FIREHOSE, 0)), firehose_error: runs.dig(FIREHOSE, 1),
        waiting: waiting.to_i, failed: failed.to_i, conflicts: conflicts.to_i,
        chat_waiting: connection.select_value(CHAT_WAITING_SQL).to_i
      )
    end

    def self.time(value)
      value.is_a?(String) ? Time.zone.parse(value) : value
    end
  end
end

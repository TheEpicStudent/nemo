module Fd
  class LinkHealth
    LANES = {
      "member_links_live" => "Last live pass",
      "member_clusters" => "Last cluster build",
      "member_links" => "Last full rebuild"
    }.freeze

    QUEUE_SQL = "SELECT count(*) AS queued, min(touched_at) AS oldest_touched_at FROM fd.member_touch".freeze
    RUNS_SQL = "SELECT source, started_at, finished_at, status, steps FROM fd.link_lane_run".freeze

    Step = Struct.new(:name, :seconds, keyword_init: true)
    Run = Struct.new(:started_at, :finished_at, :status, :steps, keyword_init: true) do
      def never? = started_at.nil?

      def running? = !never? && finished_at.nil?

      def ok? = status == "ok"

      def seconds = finished_at && started_at && (finished_at - started_at)
    end

    attr_reader :queued, :oldest_touched_at

    def self.load
      connection = MemberLink.connection
      queue = connection.select_one(QUEUE_SQL) || {}
      runs = connection.select_all(RUNS_SQL).to_h do |row|
        [row["source"], Run.new(started_at: row["started_at"]&.to_time,
          finished_at: row["finished_at"]&.to_time, status: row["status"], steps: steps_of(row["steps"]))]
      end
      new(queued: queue["queued"].to_i, oldest_touched_at: queue["oldest_touched_at"]&.to_time, runs: runs)
    end

    def self.steps_of(value)
      MemberLink.parsed(value).then { |rows| rows.is_a?(Array) ? rows : [] }
        .map { |step| Step.new(name: step["name"], seconds: step["seconds"].to_f) }
    end

    def initialize(queued:, oldest_touched_at:, runs:)
      @queued = queued
      @oldest_touched_at = oldest_touched_at
      @runs = runs
    end

    def run(source) = @runs.fetch(source) { Run.new }
  end
end

module Fd
  class LinkHealth
    LANES = {
      "member_links_live" => "Last live pass",
      "member_clusters" => "Last cluster build",
      "member_links" => "Last full rebuild"
    }.freeze

    QUEUE_SQL = "SELECT count(*) AS waiting, min(touched_at) AS oldest FROM fd.member_touch".freeze
    RUNS_SQL = "SELECT source, started_at, finished_at, status FROM fd.link_lane_run".freeze

    Run = Struct.new(:started_at, :finished_at, :status, keyword_init: true) do
      def never? = started_at.nil?

      def running? = !never? && finished_at.nil?

      def ok? = status == "ok"

      def seconds = finished_at && started_at && (finished_at - started_at)
    end

    attr_reader :waiting, :oldest

    def self.load
      connection = MemberLink.connection
      queue = connection.select_one(QUEUE_SQL) || {}
      runs = connection.select_all(RUNS_SQL).to_h do |row|
        [row["source"], Run.new(started_at: row["started_at"]&.to_time,
          finished_at: row["finished_at"]&.to_time, status: row["status"])]
      end
      new(waiting: queue["waiting"].to_i, oldest: queue["oldest"]&.to_time, runs: runs)
    end

    def initialize(waiting:, oldest:, runs:)
      @waiting = waiting
      @oldest = oldest
      @runs = runs
    end

    def run(source) = @runs.fetch(source) { Run.new }
  end
end

module Fd
  class MemberSessions
    IP_USER_THRESHOLD = 20
    DEVICE_LIMIT = 12

    Address = Struct.new(:ip, :prefix, :country, :region, :isp, :first_at, :last_at,
      :sign_in_count, :account_count, :other_user_ids, keyword_init: true) do
      def shared_range? = account_count.to_i >= IP_USER_THRESHOLD

      def shared? = account_count.to_i > 1 && !shared_range?

      def alone? = account_count.to_i <= 1

      def where
        [country, region.presence].compact_blank.join(" · ").presence
      end
    end

    Device = Struct.new(:app, :os, :addresses, :first_at, :last_at, :sign_in_count,
      keyword_init: true) do
      def name
        [app, os].compact_blank.join(" · ").presence || "Not recognised"
      end
    end

    def self.frame(user_id) = "member-sessions-#{user_id}"

    def self.with_prefix(prefix)
      return nil if prefix.nil?
      return prefix.to_s unless prefix.respond_to?(:prefix)

      "#{prefix}/#{prefix.prefix}"
    end

    def initialize(user_id)
      @user_id = user_id.to_s.upcase
    end

    attr_reader :user_id

    def rows
      @rows ||= LoginEvent.for_member(user_id).with_agent.recent_first.limit(500).to_a
    end

    def any? = rows.any?

    def devices
      @devices ||= rows.group_by { |row| [row.ua_app, row.ua_os] }
        .map { |(app, os), device_rows| device_for(app, os, device_rows) }
        .sort_by { |device| -device.last_at.to_i }
        .first(DEVICE_LIMIT)
    end

    def addresses
      @addresses ||= devices.flat_map(&:addresses).uniq(&:prefix)
    end

    def failures
      @failures ||= rows.sum(&:failures)
    end

    def anomalies
      @anomalies ||= rows.sum(&:anomalies)
    end

    def first_at = rows.map(&:first_at).compact.min

    def last_at = rows.map(&:last_at).compact.max

    def address_count = prefixes.size

    def device_count = rows.map { |row| [row.ua_app, row.ua_os] }.uniq.size

    def other_user_ids
      @other_user_ids ||= addresses.flat_map(&:other_user_ids).uniq
    end

    private

    def device_for(app, os, device_rows)
      Device.new(
        app: app, os: os, addresses: addresses_in(device_rows),
        first_at: device_rows.map(&:first_at).compact.min, last_at: device_rows.map(&:last_at).compact.max,
        sign_in_count: device_rows.sum { |row| row.seen.to_i }
      )
    end

    def addresses_in(device_rows)
      device_rows.group_by { |row| self.class.with_prefix(row.ip_prefix) }.filter_map do |prefix, rows|
        next nil if prefix.nil?

        address_for(prefix, rows)
      end.sort_by { |address| -address.last_at.to_i }
    end

    def address_for(prefix, rows)
      account_count = account_counts[prefix].to_i
      Address.new(
        ip: rows.map(&:ip).compact.first, prefix: prefix,
        country: rows.map(&:country).compact.first,
        region: rows.map(&:region).compact.first,
        isp: rows.map(&:isp).compact.first,
        first_at: rows.map(&:first_at).compact.min, last_at: rows.map(&:last_at).compact.max,
        sign_in_count: rows.sum { |row| row.seen.to_i }, account_count: account_count,
        other_user_ids: account_count.between?(2, IP_USER_THRESHOLD - 1) ? neighbours[prefix].to_a : []
      )
    end

    def prefixes
      @prefixes ||= rows.filter_map { |row| self.class.with_prefix(row.ip_prefix) }.uniq
    end

    ACCOUNT_COUNTS = <<~SQL.squish.freeze
      SELECT value, count(*) AS account_count FROM fd.member_trait
      WHERE kind = 'ip_prefix' AND value IN (:hosts)
      GROUP BY value
    SQL

    def account_counts
      @account_counts ||= begin
        counts = {}
        hosts = prefixes.index_by { |prefix| prefix.split("/").first }
        if hosts.any?
          ApplicationRecord.connection.select_all(
            ApplicationRecord.sanitize_sql([ACCOUNT_COUNTS, { hosts: hosts.keys }])
          ).each { |row| counts[hosts.fetch(row["value"])] = row["account_count"].to_i }
        end
        counts
      end
    end

    NEIGHBOURS = <<~SQL.squish.freeze
      SELECT DISTINCT ip_prefix::text AS prefix, user_id
      FROM fd.login_event
      WHERE ip_prefix = ANY(ARRAY[:prefixes]::inet[]) AND user_id <> :who
    SQL

    def neighbours
      @neighbours ||= begin
        user_ids_by_prefix = Hash.new { |hash, key| hash[key] = [] }
        shared_prefixes = prefixes.select { |prefix| account_counts[prefix].to_i.between?(2, IP_USER_THRESHOLD - 1) }
        if shared_prefixes.any?
          ApplicationRecord.connection.select_all(
            ApplicationRecord.sanitize_sql([NEIGHBOURS, { prefixes: shared_prefixes, who: user_id }])
          ).each { |row| user_ids_by_prefix[row["prefix"]] << row["user_id"] }
        end
        user_ids_by_prefix
      end
    end
  end
end

module Fd
  class LinkCompare
    SHARED_WITHIN = 1.hour
    WATCHED_NETWORKS = %w[vpn hosting tor].freeze

    Account = Struct.new(:user_id, :deactivated, :joined_at, :deactivated_at, :deactivated_by,
      :deactivation_reason, :cases, keyword_init: true)
    Attribute = Struct.new(:key, :label, :a_values, :b_values, keyword_init: true) do
      def shared = a_values.map(&:key) & b_values.map(&:key)

      def match
        return nil if a_values.empty? || b_values.empty?

        { shared: shared.size, of: (a_values.map(&:key) | b_values.map(&:key)).size }
      end
    end
    Mark = Struct.new(:user_id, :at, :ip, :network, keyword_init: true)
    Family = Struct.new(:key, :label, :total, :entries, keyword_init: true)
    Event = Struct.new(:at, :user_id, :kind, :ip, :network, :count, :shared, keyword_init: true)
    ACTIVITY_ROWS = 40

    FAMILIES = { "identity" => ["Email", "identity_signals"], "network" => ["Network", "network_signals"],
                 "device" => ["Device", "device_signals"], "name" => ["Name", "name_signals"],
                 "arrival" => ["Arrival", "arrival_signals"] }.freeze
    FAMILY_OF = FAMILIES.flat_map { |key, (_label, section)| MemberLink::SIGNALS.fetch(section, {}).keys.map { |name| [name, key] } }
      .to_h.freeze
    MARKS_PER_ACCOUNT = 300

    ATTRIBUTES = { "email" => ["Email", :emails], "ip" => ["IP", :ips], "client" => ["Client", :clients],
                   "ja4" => ["JA4", :ja4], "ja3" => ["JA3", :ja3], "channels" => ["Channels", :channels],
                   "tz" => ["Time zone", :zones] }.freeze

    SNAPSHOTS_SQL = <<~SQL.squish.freeze
      SELECT DISTINCT ON (user_id) user_id, deactivated_at, actor_id, reason
      FROM fd.evidence_snapshot WHERE user_id IN (:ids)
      ORDER BY user_id, deactivated_at DESC
    SQL
    MARKS_SQL = format(<<~SQL.squish, prefix: format(MemberTraits::PREFIX, ip: "recent.ip")).freeze
      SELECT recent.user_id, recent.first_at, host(recent.ip) AS ip, n.class AS network
      FROM (
        SELECT user_id, first_at, ip,
               row_number() OVER (PARTITION BY user_id ORDER BY first_at DESC) AS place
        FROM fd.login_event WHERE user_id IN (:ids)
      ) recent
      LEFT JOIN fd.ip_network n ON n.ip_prefix = %<prefix>s
      WHERE recent.place <= :most
      ORDER BY recent.first_at
    SQL

    def self.find(a, b, actor:, variant: nil)
      ids = [a, b].map { |user_id| user_id.to_s.strip.upcase }
      return nil unless ids.all? { |user_id| user_id.match?(AuditQuery::MEMBER_ID) } && ids.uniq.size == 2

      new(*ids, actor: actor, variant: MemberLinkShadow.variant_name(variant))
    end

    def initialize(a, b, actor:, variant: nil)
      @a = a
      @b = b
      @actor = actor
      @variant = variant
      @traits = MemberTraits.new([a, b], actor: actor)
    end

    attr_reader :a, :b, :variant

    def ids = [a, b]

    def identity? = @traits.identity?

    def link
      @link ||= if variant
        MemberLinkShadow.find_by(variant: variant, a_user_id: ids.min, b_user_id: ids.max)
      else
        MemberLink.find_by(a_user_id: ids.min, b_user_id: ids.max)
      end
    end

    def verdict
      return @verdict if defined?(@verdict)

      @verdict = LinkVerdict.find_by(a_user_id: ids.min, b_user_id: ids.max)
    end

    def evidence = link ? MemberLink.evidence_of(link.signals) : []

    def families
      totals = (link&.families || {}).transform_values(&:to_f)
      evidence.group_by { |entry| FAMILY_OF.fetch(entry["name"], "arrival") }.map do |key, entries|
        Family.new(key: key, label: FAMILIES.dig(key, 0) || key.capitalize, entries: entries,
          total: totals.fetch(key) { entries.sum { |entry| entry["score"].to_f } })
      end.sort_by { |family| -family.total }
    end

    def band = link && LinkList.band(link.score)

    def cluster_id
      return @cluster_id if defined?(@cluster_id)

      clusters = ids.map { |user_id| MemberLink.cluster_of(user_id) }
      @cluster_id = clusters.compact.size == 2 && clusters.uniq.size == 1 ? clusters.first : nil
    end

    def accounts
      @accounts ||= begin
        joined = MemberJoin.where(user_id: ids).pluck(:user_id, :joined_at).to_h
        gone = Member.where(user_id: ids, is_deleted: true).pluck(:user_id)
        snapshots = select_all(SNAPSHOTS_SQL, ids: ids).index_by { |row| row["user_id"] }
        ids.map do |user_id|
          snapshot = snapshots[user_id] || {}
          Account.new(user_id: user_id, deactivated: gone.include?(user_id), joined_at: joined[user_id],
            deactivated_at: time(snapshot["deactivated_at"]), deactivated_by: snapshot["actor_id"],
            deactivation_reason: snapshot["reason"], cases: Case.with_subject(user_id).count)
        end
      end
    end

    def account(user_id) = accounts.find { |account| account.user_id == user_id }

    def other(user_id) = account(user_id == a ? b : a)

    def alt_target
      active = accounts.reject(&:deactivated)
      return active.first if active.one?
      return nil if active.empty?

      active.max_by { |account| [account.joined_at ? 1 : 0, account.joined_at || Time.zone.at(0)] }
    end

    def returned_after_ban(user_id)
      mine = account(user_id)
      theirs = other(user_id)
      return nil if mine.deactivated || theirs.deactivated_at.nil? || mine.joined_at.nil?
      return nil unless mine.joined_at > theirs.deactivated_at

      mine.joined_at - theirs.deactivated_at
    end

    def attributes
      @attributes ||= ATTRIBUTES.map do |key, (label, reader)|
        Attribute.new(key: key, label: label, a_values: @traits.public_send(reader, a),
          b_values: @traits.public_send(reader, b))
      end
    end

    def shared_attributes = attributes.count { |attribute| attribute.shared.any? }

    def channel_ids
      row = attributes.find { |attribute| attribute.key == "channels" }
      (row.a_values + row.b_values).map(&:key)
    end

    def activity
      @activity ||= begin
        milestones = accounts.flat_map do |account|
          [(Event.new(at: account.joined_at, user_id: account.user_id, kind: "joined") if account.joined_at),
           (Event.new(at: account.deactivated_at, user_id: account.user_id, kind: "deactivated") if account.deactivated_at)]
        end.compact
        sign_ins = marks.group_by { |mark| [mark.user_id, mark.at.in_time_zone.to_date, mark.ip] }.map do |(user_id, _day, ip), group|
          Event.new(at: group.map(&:at).min, user_id: user_id, kind: "signed_in", ip: ip, network: group.first.network,
            count: group.size, shared: group.any? { |mark| shared_mark?(mark) })
        end
        kept = sign_ins.sort_by(&:at).last(ACTIVITY_ROWS - milestones.size)
        (milestones + kept).sort_by { |event| [event.at, event.kind == "signed_in" ? 1 : 0] }
      end
    end

    def marks
      @marks ||= select_all(MARKS_SQL, ids: ids, most: MARKS_PER_ACCOUNT).map do |row|
        Mark.new(user_id: row["user_id"], at: time(row["first_at"]), ip: row["ip"], network: row["network"])
      end
    end

    def shared_mark?(mark)
      @marks_by_ip ||= marks.select(&:ip).group_by(&:ip)
      @marks_by_ip.fetch(mark.ip, []).any? do |other_mark|
        other_mark.user_id != mark.user_id && (other_mark.at - mark.at).abs < SHARED_WITHIN
      end
    end

    def watched_mark?(mark) = WATCHED_NETWORKS.include?(mark.network)

    def user_ids_named = ids + [verdict&.decided_by].compact + accounts.filter_map(&:deactivated_by)

    def record_reads!
      AccessLog.record_many!(actor: @actor, subject_user_ids: ids, field_class: "links")
      AccessLog.record_many!(actor: @actor, subject_user_ids: ids, field_class: "login") if identity?
    end

    private

    def select_all(sql, binds)
      ApplicationRecord.connection.select_all(ApplicationRecord.sanitize_sql([sql, binds])).to_a
    end

    def time(value)
      value.is_a?(String) ? Time.zone.parse(value) : value
    end
  end
end

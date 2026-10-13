module Fd
  class ClusterView
    TIMELINE_DAYS = 60

    Member = Struct.new(:user_id, :joined_at, :active, :deactivated, keyword_init: true)
    Edge = Struct.new(:a_user_id, :b_user_id, :score, :top_signal, :signals, :label, :last_seen, :verdict,
      :decided_by, :decided_at, :note, keyword_init: true) do
      def touches?(user_id) = a_user_id == user_id || b_user_id == user_id

      def other(user_id) = a_user_id == user_id ? b_user_id : a_user_id

      def evidence = MemberLink.evidence_of(signals)

      def apart? = ClusterView::APART.include?(verdict)
    end
    Return = Struct.new(:user_id, :banned_id, :after, keyword_init: true)
    SharedValue = Struct.new(:name, :label, :value, :user_ids, :score, keyword_init: true)

    APART = %w[different_people].freeze
    SHARED_VALUES = 8
    Sighting = Struct.new(:user_id, :hour, :ip, :hits, keyword_init: true)
    Snapshot = Struct.new(:id, :user_id, :deactivated_at, :source, :actor_id, :reason, :identity, :traits,
      :links, keyword_init: true) do
      def email = (identity || {})["email"]

      def addresses = (traits || []).select { |trait| trait["kind"] == "ip" }.map { |trait| trait["value"] }

      def clients = (traits || []).filter_map { |trait| trait["agent"] if trait["kind"] == "ua_id" }.uniq
    end

    MEMBERS_SQL = <<~SQL.squish.freeze
      SELECT c.user_id, c.active, c.ring, c.conflict, j.joined_at, coalesce(m.is_deleted, false) AS deactivated
      FROM fd.member_cluster c
      LEFT JOIN fd.member_joins j ON j.user_id = c.user_id
      LEFT JOIN fd.member m ON m.user_id = c.user_id
      WHERE c.cluster_id = :cluster_id
      ORDER BY j.joined_at NULLS LAST, c.user_id
    SQL

    EDGES_SQL = <<~SQL.squish.freeze
      SELECT coalesce(l.a_user_id, v.a_user_id) AS a_user_id, coalesce(l.b_user_id, v.b_user_id) AS b_user_id,
             l.score, l.top_signal, l.signals, l.label, l.last_seen, v.verdict, v.decided_by, v.decided_at, v.note
      FROM (SELECT * FROM fd.member_link
            WHERE a_user_id IN (:ids) AND b_user_id IN (:ids)) l
      FULL JOIN (SELECT * FROM fd.member_link_verdict
                 WHERE a_user_id IN (:ids) AND b_user_id IN (:ids)) v
        ON v.a_user_id = l.a_user_id AND v.b_user_id = l.b_user_id
      ORDER BY l.score DESC NULLS LAST, 1, 2
    SQL

    SIGHTINGS_SQL = <<~SQL.squish.freeze
      SELECT user_id, hour, host(ip) AS ip, sum(hits) AS hits
      FROM fd.login_event
      WHERE user_id IN (:ids) AND ip IS NOT NULL AND hour >= :since
      GROUP BY user_id, hour, ip
      ORDER BY hour
    SQL

    SNAPSHOTS_SQL = <<~SQL.squish.freeze
      SELECT id, user_id, deactivated_at, source, actor_id, reason, identity, traits, links
      FROM fd.evidence_snapshot
      WHERE user_id IN (:ids)
      ORDER BY deactivated_at DESC
    SQL

    def self.find(cluster_id)
      view = new(cluster_id.to_s.upcase)
      view.members.any? ? view : nil
    end

    def initialize(cluster_id)
      @cluster_id = cluster_id
    end

    attr_reader :cluster_id

    def members
      @members ||= rows(MEMBERS_SQL, cluster_id: cluster_id).map do |row|
        @flags ||= { ring: flag(row["ring"]), conflict: flag(row["conflict"]) }
        Member.new(user_id: row["user_id"], joined_at: time(row["joined_at"]),
          active: flag(row["active"]), deactivated: flag(row["deactivated"]))
      end
    end

    def ids = members.map(&:user_id)

    def ring? = members.any? && @flags[:ring]

    def conflict? = members.any? && @flags[:conflict]

    def active = members.select(&:active)

    def edges
      @edges ||= rows(EDGES_SQL, ids: ids).map do |row|
        Edge.new(a_user_id: row["a_user_id"], b_user_id: row["b_user_id"],
          score: row["score"]&.to_f, top_signal: row["top_signal"],
          signals: MemberLink.parsed(row["signals"]), label: row["label"], last_seen: time(row["last_seen"]),
          verdict: row["verdict"], decided_by: row["decided_by"], decided_at: time(row["decided_at"]),
          note: row["note"])
      end
    end

    def links = edges.select(&:score)

    def verdict_edges = edges.select(&:verdict).sort_by { |edge| -edge.decided_at.to_i }

    def conflicts = edges.select(&:apart?)

    def links_of(user_id) = links.select { |edge| edge.touches?(user_id) }.sort_by { |edge| -edge.score }

    def deactivated = members.select(&:deactivated)

    def first_join = members.filter_map(&:joined_at).min

    def last_join = members.filter_map(&:joined_at).max

    def member(user_id) = members.find { |member| member.user_id == user_id }

    def snapshot_of(user_id)
      @snapshot_of ||= snapshots.group_by(&:user_id).transform_values(&:first)
      @snapshot_of[user_id]
    end

    def returns
      @returns ||= begin
        bans = snapshots.select(&:deactivated_at)
        members.reject(&:deactivated).filter_map do |member|
          next if member.joined_at.nil?

          ban = bans.select { |snapshot| snapshot.user_id != member.user_id && snapshot.deactivated_at < member.joined_at }
            .max_by(&:deactivated_at)
          ban && Return.new(user_id: member.user_id, banned_id: ban.user_id, after: member.joined_at - ban.deactivated_at)
        end
      end
    end

    def shared_values
      @shared_values ||= links.each_with_object({}) do |edge, values|
        edge.evidence.each do |entry|
          next if entry["value"].blank?

          key = [entry["name"], entry["value"]]
          values[key] ||= SharedValue.new(name: entry["name"], label: entry["label"], value: entry["value"],
            user_ids: [], score: entry["score"].to_f)
          values[key].user_ids |= [edge.a_user_id, edge.b_user_id]
        end
      end.values.sort_by { |shared| [-shared.user_ids.size, -shared.score] }.first(SHARED_VALUES)
    end

    def since
      oldest = members.filter_map(&:joined_at).min
      floor = TIMELINE_DAYS.days.ago.beginning_of_day
      oldest && oldest > floor ? oldest.beginning_of_hour : floor
    end

    def sightings
      @sightings ||= rows(SIGHTINGS_SQL, ids: ids, since: since).map do |row|
        Sighting.new(user_id: row["user_id"], hour: time(row["hour"]), ip: row["ip"],
          hits: row["hits"].to_i)
      end
    end

    def shared_ips
      @shared_ips ||= sightings.group_by(&:ip).select { |_ip, ip_sightings| ip_sightings.map(&:user_id).uniq.size > 1 }
        .keys.sort
    end

    def snapshots
      @snapshots ||= rows(SNAPSHOTS_SQL, ids: ids).map do |row|
        Snapshot.new(id: row["id"].to_i, user_id: row["user_id"], deactivated_at: time(row["deactivated_at"]),
          source: row["source"], actor_id: row["actor_id"], reason: row["reason"],
          identity: MemberLink.parsed(row["identity"]), traits: MemberLink.parsed(row["traits"]),
          links: MemberLink.parsed(row["links"]))
      end
    end

    def map_data
      joined = members.filter_map(&:joined_at)
      {
        nodes: members.map do |member|
          { id: member.user_id, joined: member.joined_at&.iso8601, active: member.active,
            deactivated: member.deactivated, oldest: member.user_id == cluster_id }
        end,
        edges: edges.map do |edge|
          { a: edge.a_user_id, b: edge.b_user_id, score: edge.score, verdict: edge.verdict,
            band: band_of(edge.score) }
        end,
        first: joined.min&.iso8601, last: joined.max&.iso8601
      }
    end

    def timeline_data
      {
        rows: members.map(&:user_id),
        since: since.iso8601,
        until: Time.current.iso8601,
        shared: shared_ips,
        marks: sightings.map { |sighting| { user: sighting.user_id, hour: sighting.hour.iso8601, ip: sighting.ip, hits: sighting.hits } }
      }
    end

    private

    def band_of(score)
      return "verdict" if score.nil?
      return "certain" if score >= MemberLink::CERTAIN
      return "strong" if score >= MemberLink::STRONG

      "weak"
    end

    def rows(sql, binds)
      return [] if binds.key?(:ids) && binds[:ids].empty?

      ApplicationRecord.connection.select_all(ApplicationRecord.sanitize_sql([sql, binds])).to_a
    end

    def flag(value) = ActiveModel::Type::Boolean.new.cast(value) || false

    def time(value)
      return nil if value.nil?

      value.is_a?(String) ? Time.zone.parse(value) : value
    end
  end
end

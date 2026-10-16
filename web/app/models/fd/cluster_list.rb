module Fd
  class ClusterList
    FILTERS = { "all" => "All", "ring" => "Rings", "evasion" => "Evasion", "conflict" => "Conflicts" }.freeze
    CONDITIONS = { "all" => "true", "ring" => "ring", "evasion" => "returns > 0", "conflict" => "conflict" }.freeze
    LIMIT = 60
    SHOWN_MEMBERS = 40

    Card = Struct.new(:cluster_id, :accounts, :active, :ring, :conflict, :returns, :last_join, :top_signal,
      :members, :edges, keyword_init: true) do
      def deactivated = accounts - active
    end
    Member = Struct.new(:user_id, :deactivated, :joined_at, keyword_init: true)
    Edge = Struct.new(:a_user_id, :b_user_id, :score, :verdict, keyword_init: true)

    SUMMARY = <<~SQL.squish.freeze
      WITH clusters AS (
        SELECT c.cluster_id, max(c.accounts) AS accounts, count(*) FILTER (WHERE c.active) AS active,
               bool_or(c.ring) AS ring, bool_or(c.conflict) AS conflict, max(j.joined_at) AS last_join
        FROM fd.member_cluster c
        LEFT JOIN fd.member_joins j ON j.user_id = c.user_id
        GROUP BY c.cluster_id
      ), returns AS (
        SELECT deactivated_member.cluster_id, count(DISTINCT returned_member.user_id) AS returns
        FROM fd.member_cluster deactivated_member
        JOIN fd.evidence_snapshot s ON s.user_id = deactivated_member.user_id
        JOIN fd.member_cluster returned_member
          ON returned_member.cluster_id = deactivated_member.cluster_id AND returned_member.active
        JOIN fd.member_joins j ON j.user_id = returned_member.user_id AND j.joined_at > s.deactivated_at
        GROUP BY deactivated_member.cluster_id
      )
      SELECT clusters.*, coalesce(returns.returns, 0) AS returns
      FROM clusters LEFT JOIN returns USING (cluster_id)
    SQL

    MEMBERS_SQL = <<~SQL.squish.freeze
      SELECT cluster_id, user_id, deactivated, joined_at FROM (
        SELECT c.cluster_id, c.user_id, coalesce(m.is_deleted, false) AS deactivated, j.joined_at,
               row_number() OVER (PARTITION BY c.cluster_id ORDER BY j.joined_at NULLS LAST, c.user_id) AS member_rank
        FROM fd.member_cluster c
        LEFT JOIN fd.member m ON m.user_id = c.user_id
        LEFT JOIN fd.member_joins j ON j.user_id = c.user_id
        WHERE c.cluster_id IN (:ids)
      ) ranked
      WHERE member_rank <= :shown
      ORDER BY cluster_id, member_rank
    SQL

    EDGES_SQL = <<~SQL.squish.freeze
      SELECT l.a_user_id, l.b_user_id, l.score, v.verdict
      FROM fd.member_link l
      LEFT JOIN fd.member_link_verdict v ON v.a_user_id = l.a_user_id AND v.b_user_id = l.b_user_id
      WHERE l.a_user_id IN (:ids) AND l.b_user_id IN (:ids)
    SQL

    TOP_SIGNALS_SQL = <<~SQL.squish.freeze
      SELECT DISTINCT ON (ca.cluster_id) ca.cluster_id, l.top_signal
      FROM fd.member_link l
      JOIN fd.member_cluster ca ON ca.user_id = l.a_user_id
      JOIN fd.member_cluster cb ON cb.user_id = l.b_user_id AND cb.cluster_id = ca.cluster_id
      WHERE ca.cluster_id IN (:ids) AND l.top_signal IS NOT NULL
      GROUP BY ca.cluster_id, l.top_signal
      ORDER BY ca.cluster_id, count(*) DESC, l.top_signal
    SQL

    def initialize(params = {})
      @params = params
    end

    def filter
      requested = @params[:filter].to_s
      FILTERS.key?(requested) ? requested : "all"
    end

    def counts
      @counts ||= begin
        columns = CONDITIONS.map { |key, condition| "count(*) FILTER (WHERE #{condition}) AS #{key}" }
        row = select_all("SELECT #{columns.join(', ')} FROM (#{SUMMARY}) summary").first || {}
        FILTERS.keys.index_with { |key| row[key].to_i }
      end
    end

    def cards
      @cards ||= begin
        rows = select_all("SELECT * FROM (#{SUMMARY}) summary WHERE #{CONDITIONS.fetch(filter)} " \
                          "ORDER BY last_join DESC NULLS LAST, cluster_id LIMIT :limit", limit: LIMIT)
        ids = rows.map { |row| row["cluster_id"] }
        members = members_by_cluster(ids)
        edges = edges_by_cluster(members)
        tops = ids.empty? ? {} : select_all(TOP_SIGNALS_SQL, ids: ids).to_h { |row| [row["cluster_id"], row["top_signal"]] }
        rows.map { |row| build_card(row, members, edges, tops) }
      end
    end

    def user_ids = cards.flat_map { |card| [card.cluster_id] + card.members.map(&:user_id) }

    private

    def members_by_cluster(ids)
      return {} if ids.empty?

      flag = ActiveModel::Type::Boolean.new
      select_all(MEMBERS_SQL, ids: ids, shown: SHOWN_MEMBERS).group_by { |row| row["cluster_id"] }
        .transform_values do |rows|
          rows.map do |row|
            Member.new(user_id: row["user_id"], deactivated: flag.cast(row["deactivated"]) || false,
              joined_at: row["joined_at"])
          end
        end
    end

    def edges_by_cluster(members)
      cluster_of = members.flat_map { |cluster_id, rows| rows.map { |member| [member.user_id, cluster_id] } }.to_h
      return {} if cluster_of.empty?

      select_all(EDGES_SQL, ids: cluster_of.keys).each_with_object(Hash.new { |hash, key| hash[key] = [] }) do |row, grouped|
        cluster_id = cluster_of[row["a_user_id"]]
        next unless cluster_id && cluster_id == cluster_of[row["b_user_id"]]

        grouped[cluster_id] << Edge.new(a_user_id: row["a_user_id"], b_user_id: row["b_user_id"],
          score: row["score"]&.to_f, verdict: row["verdict"])
      end
    end

    def build_card(row, members, edges, tops)
      flag = ActiveModel::Type::Boolean.new
      cluster_id = row["cluster_id"]
      Card.new(cluster_id: cluster_id, accounts: row["accounts"].to_i, active: row["active"].to_i,
        ring: flag.cast(row["ring"]) || false, conflict: flag.cast(row["conflict"]) || false,
        returns: row["returns"].to_i, last_join: time(row["last_join"]),
        top_signal: tops[cluster_id] && MemberLink.label_for(tops[cluster_id]),
        members: members.fetch(cluster_id, []), edges: edges.fetch(cluster_id, []))
    end

    def select_all(sql, binds = {})
      ApplicationRecord.connection.select_all(ApplicationRecord.sanitize_sql([sql, binds])).to_a
    end

    def time(value)
      value.is_a?(String) ? Time.zone.parse(value) : value
    end
  end
end

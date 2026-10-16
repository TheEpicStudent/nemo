module Fd
  class AuditContext
    RELATED = 10
    UUID = /\A\h{8}-\h{4}-\h{4}-\h{4}-\h{12}\z/

    Device = Struct.new(:app, :os, :ua, keyword_init: true)
    LoginLocation = Struct.new(:country, :network, :kind, :accounts, keyword_init: true)

    CONTEXT_SQL = <<~SQL.squish.freeze
      SELECT u.ua, u.app, u.os, n.country, n.network, n.class AS kind,
             (SELECT count(DISTINCT l.user_id) FROM fd.login_event l WHERE l.ip = e.ip) AS accounts
      FROM (SELECT ua_id, ip FROM slack.audit_event WHERE id = :id
            UNION ALL
            SELECT ua_id, ip FROM slack.audit_view WHERE id = :id) e
      LEFT JOIN slack.user_agent u ON u.id = e.ua_id
      LEFT JOIN fd.ip_network n
        ON n.ip_prefix = network(set_masklen(e.ip, CASE WHEN family(e.ip) = 4 THEN 24 ELSE 64 END))
      LIMIT 1
    SQL

    def initialize(row, query)
      @row = row
      @query = query
    end

    attr_reader :row

    def device
      return nil unless context_row

      result = Device.new(app: context_row["app"], os: context_row["os"], ua: context_row["ua"])
      result.ua || result.app ? result : nil
    end

    def login_location
      return nil unless context_row && @query.identity?

      result = LoginLocation.new(country: context_row["country"], network: context_row["network"], kind: context_row["kind"],
        accounts: context_row["accounts"].to_i)
      result.country || result.network ? result : nil
    end

    def actor_email = payload.dig("actor", "user", "email")

    def entity_name
      kind = payload.dig("entity", "type")
      return nil if kind.blank?

      entity = payload.dig("entity", kind)
      entity.is_a?(Hash) ? (entity["name"].presence || entity["title"].presence) : nil
    end

    def category
      key = AuditCatalogue::ACTIONS.dig(row.verb.to_s, "category")
      key && AuditCatalogue.category_label(key)
    end

    def related_params
      around = @query.pivots(row).find { |pivot| pivot.kind == "around" }
      around&.params
    end

    def related
      @related ||= begin
        params = related_params
        params ? AuditQuery.new(params, actor: @query.actor).rows.reject { |related_row| related_row.id == row.id } : []
      end
    end

    def visible_related = related.first(RELATED)

    def more_related? = related.size > RELATED

    def member_id
      [row.actor_id, row.subject_id].find { |user_id| user_id.to_s.match?(AuditQuery::MEMBER_ID) }
    end

    def linked_accounts
      return 0 if member_id.nil? || !@query.actor&.may?("member.links")

      MemberLink.link_counts_for(member_id).count
    end

    private

    def payload
      row.slack? && row.after.is_a?(Hash) ? row.after : {}
    end

    def context_row
      return @context_row if defined?(@context_row)

      @context_row = row.slack? && row.id.to_s.match?(UUID) ? lookup : nil
    end

    def lookup
      ApplicationRecord.connection.select_one(ApplicationRecord.sanitize_sql([CONTEXT_SQL, { id: row.id }]))
    end
  end
end

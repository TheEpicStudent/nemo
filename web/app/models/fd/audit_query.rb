module Fd
  class AuditQuery
    Facet = Struct.new(:key, :label, :value, :value_label, :options, :on, :kind,
      keyword_init: true)
    View = Struct.new(:key, :label, :count, :current, keyword_init: true)
    Row = Struct.new(:source, :id, :at, :actor_id, :actor_kind, :verb, :entity_kind,
      :entity_id, :entity_ref, :subject_id, :before, :after, :detail, :channel, :app, :session,
      :addressed, :address, keyword_init: true) do
      def ours? = source == FIRE_ENGINE

      def slack? = source == SLACK

      def read? = source == READ

      def api? = source == API

      def changed_keys
        ((after || {}).keys | (before || {}).keys).sort
      end

      def diff?
        ours? && changed_keys.any?
      end

      def raw
        return after if slack?

        { "before" => before, "after" => after }.compact.presence
      end

      def raw?
        raw.present? || detail.present?
      end

      def was(key) = (before || {})[key]

      def now(key) = (after || {})[key]

      def ip = address.presence || (detail || {})["ip_address"]

      def app_name = (detail || {}).dig("app", "name")
    end

    FIRE_ENGINE = "fire_engine".freeze
    SLACK = "slack".freeze
    READ = "read".freeze
    API = "api".freeze
    SOURCES = [FIRE_ENGINE, SLACK, READ, API].freeze

    LIMIT = 100
    MEMBER_ID = /\A[UW][A-Z0-9]{2,}\z/
    WORD = /\A[a-z0-9_.]{2,60}\z/i

    VIEWS = {
      "everything" => "Everything",
      "engine" => "Fire Engine",
      "slack" => "Slack",
      "reads" => "Identity reads",
      "api" => "Public API",
      "refusals" => "Refusals"
    }.freeze

    TABS = VIEWS.keys.freeze

    VIEW_SOURCES = {
      "everything" => SOURCES,
      "engine" => [FIRE_ENGINE],
      "slack" => [SLACK],
      "reads" => [READ],
      "api" => [API],
      "refusals" => [FIRE_ENGINE]
    }.freeze


    TERM_KEY = "q".freeze
    KEYS = %w[view q before_at before_id after_at after_id on live].freeze

    DEFAULT_VIEW = "slack".freeze
    NO_VIEW = "none".freeze

    HELP = {
      "86.12.44.9" => "an address, and who used it",
      "86.12.44.0/24" => "a range",
      "kid@school.example" => "an email",
      "domain:throwaway.example" => "an email domain",
      "@handle" => "about them",
      "actor:@handle" => "by them",
      "did:deactivated" => "one event",
      "category:people" => "one kind of event",
      "network:vpn" => "a network class: stable, rotating, vpn, hosting or tor",
      "country:DE" => "one country, from the address",
      "show:high_volume" => "previews, downloads and list edits",
      "in:#ask" => "one channel",
      "source:slack" => "one log",
      "is:nemo" => "nemo, not a person",
      "by:me" => "by you",
      "after:2026-09-01" => "from a date",
      "before:2026-09-20" => "up to a date",
      "last:24h" => "the last 24 hours",
      "app:A0123ABCD" => "one app",
      "session:123456" => "one sign-in session",
      "invite spam" => "free text"
    }.freeze

    ROW_BY_ID = {
      FIRE_ENGINE => "a.id::text = :id",
      SLACK => "e.id::text = :id",
      READ => "'r' || l.id::text = :id"
    }.freeze

    def self.find_one(source, id, actor: nil)
      return nil unless SOURCES.include?(source) && id.present?

      new({ "when" => "any", "view" => view_for(source) }, actor: actor).send(:find_row, source, id)
    end

    def self.view_for(source)
      VIEW_SOURCES.key(Array(source)) || "everything"
    end

    def initialize(params = {}, actor: nil)
      @params = params
      @actor = actor
    end

    attr_reader :actor

    def term
      @term ||= @params[TERM_KEY].to_s.strip
    end

    def search
      @search ||= AuditSearch.parse(term, actor: actor)
    end

    def terms = search.terms

    def searching? = search.any?

    ENGINE_READ = "access.read".freeze
    SLACK_READ = "audit.read".freeze
    IDENTITY_READ = "identity.read".freeze

    def may_engine?
      return @may_engine if defined?(@may_engine)

      @may_engine = actor.present? && actor.may?(ENGINE_READ)
    end

    def may_slack?
      return @may_slack if defined?(@may_slack)

      @may_slack = actor.present? && actor.may?(SLACK_READ)
    end

    def identity? = search.identity?

    def identity_refused? = search.identity_terms? && !identity?

    def allowed_views
      views = VIEWS
      views = views.except(*ENGINE_ONLY) unless may_engine?
      views = views.except(*SLACK_ONLY) unless may_slack?
      views
    end

    ENGINE_ONLY = %w[engine refusals].freeze
    SLACK_ONLY = %w[slack].freeze

    def may_see?(source)
      case source
      when FIRE_ENGINE then may_engine?
      when SLACK then may_slack?
      else true
      end
    end

    def default_view = may_slack? ? DEFAULT_VIEW : "everything"

    def view
      requested = @params["view"].to_s
      return nil if requested == NO_VIEW

      allowed_views.key?(requested) ? requested : default_view
    end

    def view_label = VIEWS.fetch(view)

    def views
      counts = view_counts
      allowed_views.map do |key, label|
        View.new(key: key, label: label, count: counts.fetch(key, 0), current: key == view)
      end
    end

    def query_params
      searching? ? { TERM_KEY => term } : {}
    end

    def scope_params
      params = group_params.merge(live_params)
      return params if view.nil? || view == default_view

      { "view" => view }.merge(params)
    end

    def live? = @params["live"].to_s == "1"

    def newest_page? = @params["before_at"].blank? && @params["after_at"].blank? && jump_date.nil?

    def live_params = live? ? { "live" => "1" } : {}

    LIVE_ACTIONS = %w[
      anomaly user_sessions_reset_by_anomaly_event_response user_session_reset_by_admin
      bulk_session_reset_by_admin cli_login user_password_reset_requested
      user_deactivated user_reactivated guest_deactivated guest_reactivated user_email_updated
      email_change_confirmed
      role_assigned role_removed role_change_to_user permissions_assigned permissions_removed
      audit_logs_export_json_started audit_logs_records_searched_anomaly
      app_installed app_approved app_scopes_expanded app_token_preserved app_collaborator_added
      private_message_forwarded file_public_link_created file_malicious_content_detected
      private_channel_converted_to_public external_shared_channel_connected
      external_shared_channel_invite_accepted public_channel_deleted private_channel_deleted
      channel_retention_changed
      refused granted revoked read exported turned_on turned_off performed reversed
    ].freeze
    LIVE_ACTION_PREFIXES = %w[pref.].freeze
    LIVE_SUBJECT_KINDS = %w[actor about ip email domain session].freeze
    LIVE_NETWORKS = %w[tor].freeze
    LIVE_VIEWS = %w[reads refusals].freeze

    def live_watch
      return nil unless live_push?

      {
        "sources" => selected_sources,
        "actions" => (view == "refusals" ? ["refused"] : watched_actions).presence,
        "actors" => search.of("actor").presence,
        "subjects" => search.of("about").presence
      }.compact
    end

    def live_push?
      return true if LIVE_VIEWS.include?(view)
      return true if terms.any? { |term| LIVE_SUBJECT_KINDS.include?(term.kind) }
      return true if search.of("network").intersect?(LIVE_NETWORKS)

      watched_actions.any? && watched_actions.all? { |action| live_action?(action) }
    end

    def watched_actions
      @watched_actions ||= (search.of("action") + AuditCatalogue.actions_in(search.of("category"))).uniq
    end

    def live_action?(action)
      LIVE_ACTIONS.include?(action) || LIVE_ACTION_PREFIXES.any? { |prefix| action.start_with?(prefix) }
    end

    def live_toggle_params
      live? ? to_params.except("live") : to_params.merge("live" => "1")
    end

    def to_params = query_params.merge(scope_params)

    def view_params(key)
      params = query_params.merge(group_params)
      key == default_view ? params : params.merge("view" => key)
    end

    def without_params(term_value)
      params = query_params.merge(scope_params)
      remaining = search.without(term_value)
      remaining.present? ? params.merge(TERM_KEY => remaining) : params.except(TERM_KEY)
    end

    def with_params(term_value)
      query_params.merge(scope_params).merge(TERM_KEY => [term, term_value].compact_blank.join(" ").strip)
    end

    RANGE_KINDS = %w[after before last].freeze
    HOUR_STAMP = /\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\z/

    def range_params(start_on, end_on)
      start = start_on.to_s
      ending = end_on.presence&.to_s || start
      remaining = terms.reject { |query_term| RANGE_KINDS.include?(query_term.kind) }.map { |query_term| search.label_for(query_term) }
      scope_params.merge(TERM_KEY => (remaining + range_terms(start, ending)).join(" "))
    rescue Date::Error, ArgumentError, NoMethodError
      to_params
    end

    def range_terms(start, ending)
      if start.match?(HOUR_STAMP) && ending.match?(HOUR_STAMP)
        from, upto = [Time.zone.parse(start), Time.zone.parse(ending)].minmax
        return ["after:#{from.strftime(AuditSearch::MINUTE)}", "before:#{(upto + 1.hour).strftime(AuditSearch::MINUTE)}"]
      end

      from, upto = [Date.iso8601(start), Date.iso8601(ending)].minmax
      ["after:#{from.iso8601}", "before:#{(upto + 1).iso8601}"]
    end

    def set_params(kinds, value = nil)
      kinds = Array(kinds)
      remaining = terms.reject { |query_term| kinds.include?(query_term.kind) }.map { |query_term| search.label_for(query_term) }
      remaining << "#{kinds.first}:#{value}" if value
      params = scope_params
      remaining.any? ? params.merge(TERM_KEY => remaining.join(" ")) : params
    end

    def rows
      @rows ||= paged_rows
    end

    def back_params
      return nil if rows.empty? || first_page?

      first = rows.first
      to_params.merge("after_at" => first.at.iso8601(6), "after_id" => first.id)
    end

    def identity_reads
      reads = {}
      reads["identity_search"] = visible_member_ids if search.identity_terms? && identity?
      reads["audit"] = search.of("actor") | search.of("about") if selected_sources.include?(SLACK)
      reads.transform_values { |ids| ids.grep(MEMBER_ID) }.reject { |_, ids| ids.empty? }
    end

    def visible_member_ids
      return group == "actor" ? groups.map(&:key) : [] if group

      rows.flat_map { |row| [row.actor_id, row.subject_id, row.entity_id] }.compact.uniq
    end

    Pivot = Struct.new(:label, :params, :kind, :value, keyword_init: true)
    PIVOT_WINDOW = 15.minutes
    HIGH_VOLUME_TERM = "show:high_volume".freeze

    def pivots(row)
      member_actor = row.actor_id.to_s.match?(MEMBER_ID)
      pivots = []
      pivots << value_pivot("Actor", "actor", row.actor_id) if member_actor
      pivots << value_pivot("Event", "action", row.verb) if row.verb.present?
      pivots << value_pivot("IP", "ip", row.ip) if row.ip.present?
      pivots << value_pivot("Channel", "channel", row.channel) if row.channel.present?
      pivots << value_pivot("App", "app", row.app) if row.app.present?
      pivots << Pivot.new(label: "Actor ±15 min", kind: "around", params: around_params(row)) if member_actor
      if member_actor && row.session.present?
        pivots << Pivot.new(label: "Session", kind: "session", value: row.session,
          params: reset_params("actor:#{row.actor_id}", "session:#{row.session}", HIGH_VOLUME_TERM))
      end
      pivots.compact
    end

    def value_pivot(label, kind, value)
      return nil if search.of(kind) == [value]

      remaining = terms.reject { |query_term| query_term.kind == kind }.map { |query_term| search.label_for(query_term) }
      Pivot.new(label: label, kind: kind, value: value,
        params: scope_params.except("group").merge(TERM_KEY => (remaining << "#{kind}:#{value}").join(" ")))
    end

    def around_params(row)
      at = row.at.in_time_zone
      from = (at - PIVOT_WINDOW).change(sec: 0)
      upto = (at + PIVOT_WINDOW).change(sec: 0) + 1.minute
      reset_params("actor:#{row.actor_id}", "after:#{from.strftime(AuditSearch::MINUTE)}",
        "before:#{upto.strftime(AuditSearch::MINUTE)}", HIGH_VOLUME_TERM)
    end

    def reset_params(*query_terms) = scope_params.except("group").merge(TERM_KEY => query_terms.join(" "))

    NETWORK_ATTRIBUTE = "(SELECT n.%<field>s FROM fd.ip_network n WHERE n.ip_prefix = " \
                 "network(set_masklen(%<ip>s, CASE WHEN family(%<ip>s) = 4 THEN 24 ELSE 64 END)))".freeze
    ROW_IP = "(events.ip::inet)".freeze

    GROUPS = {
      "actor" => "Actor", "action" => "Event", "address" => "IP",
      "channel" => "Channel", "app" => "App", "country" => "Country"
    }.freeze
    GROUP_COLUMNS = {
      "actor" => "actor_id", "action" => "verb", "address" => "ip",
      "channel" => "channel", "app" => "app",
      "country" => format(NETWORK_ATTRIBUTE, field: "country", ip: ROW_IP)
    }.freeze
    GROUP_TERMS = {
      "actor" => "actor", "action" => "action", "address" => "ip",
      "channel" => "in", "app" => "app", "country" => "country"
    }.freeze
    GROUP_LIMIT = 100

    Group = Struct.new(:key, :count, :first_at, :last_at, :name, keyword_init: true)

    def allowed_groups
      identity? ? GROUPS : GROUPS.except("address")
    end

    def group
      requested = @params["group"].to_s
      allowed_groups.key?(requested) ? requested : nil
    end

    def group_label = GROUPS[group]

    def group_params = group ? { "group" => group } : {}

    def groups
      @groups ||= fetch_groups
    end

    def groups_slow? = @groups_slow == true

    def group_summary
      "#{number_label(groups.size)} of #{number_label(@group_total.to_i)} #{group_label.downcase.pluralize(@group_total.to_i)}"
    end

    def group_params_for(group_row)
      with_params("#{GROUP_TERMS.fetch(group)}:#{group_row.key}").except("group")
    end

    def jump_date
      Date.iso8601(@params["on"].to_s)
    rescue Date::Error
      nil
    end

    def more?
      @more ||= rows.size >= LIMIT
    end

    def next_params
      return nil unless more?

      last = rows.last
      to_params.merge("before_at" => last.at.iso8601(6), "before_id" => last.id)
    end

    def total
      @total ||= select_rows(count_sql).first["event_count"].to_i
    end

    HISTOGRAM_DAYS = 30
    HOURLY_UP_TO = 2.days
    FIRST_DAY = Date.new(2025, 11, 1)
    HISTOGRAM_TIMEOUT = "SET LOCAL statement_timeout = '8s'".freeze
    HISTOGRAM_WINDOW = "at >= :histogram_from AND at < :histogram_upto".freeze

    def histogram_span
      upto = [upto_at, Time.current].compact.min
      from = from_at || (upto.to_date - (HISTOGRAM_DAYS - 1)).in_time_zone
      [[from, FIRST_DAY.in_time_zone].max, upto]
    end

    def hourly?
      from, upto = histogram_span
      upto - from <= HOURLY_UP_TO
    end

    def histogram
      from, upto = histogram_span
      return [] if from >= upto || selected_sources.empty?

      unit = hourly? ? "hour" : "day"
      counts = ApplicationRecord.transaction do
        ApplicationRecord.connection.execute(HISTOGRAM_TIMEOUT)
        select_rows(histogram_sql, unit: unit, zone: Time.zone.tzinfo.name, histogram_from: from, histogram_upto: upto)
          .to_h { |row| [bin_key(row["bin"]), row["event_count"].to_i] }
      end
      histogram_bins(from, upto).map { |bin| [bin, counts.fetch(bin_key(bin), 0)] }
    rescue ActiveRecord::QueryCanceled
      []
    end

    def histogram_bins(from, upto)
      return (from.to_date..(upto - 1).to_date).to_a unless hourly?

      first = from.beginning_of_hour
      (0...((upto - first) / 1.hour).ceil).map { |step| first + step.hours }
    end

    def bin_key(value)
      at = value.is_a?(String) ? Time.zone.parse(value) : value
      hourly? ? at.strftime(AuditSearch::MINUTE) : at.to_date.iso8601
    end

    def title
      return "#{view_label} matching #{term}" if view && searching?
      return view_label if view

      terms.any? ? "Everything #{terms.map(&:label).to_sentence}" : "Everything"
    end

    def summary
      "#{number_label(rows.size)} of #{total_label}"
    end

    COUNT_CEILING = 10_000

    def total_label
      total > COUNT_CEILING ? "#{number_label(COUNT_CEILING)}+" : number_label(total)
    end

    def empty_note
      return "Requires identity.read" if identity_refused?
      return "No events" if searching?

      case view
      when "reads" then "No identity reads"
      when "refusals" then "No refusals"
      else "No events"
      end
    end

    def suggestions
      known_verbs.first(SUGGESTED)
    end

    FACETS = %w[category action network is].freeze
    FACET_TERMS = { "category" => %w[category], "action" => %w[action], "network" => %w[network],
                    "is" => %w[is] }.freeze
    FACET_LIMIT = 200
    ACTOR_TYPE_COUNTS = <<~SQL.freeze
      SELECT count(*) FILTER (WHERE actor_kind = 'human' AND actor_id IS NOT NULL) AS human,
             count(*) FILTER (WHERE actor_kind <> 'human') AS nemo,
             count(*) FILTER (WHERE actor_id IS NULL) AS nobody
      FROM (UNION_SQL) events
    SQL

    def facet(key)
      return {} unless FACETS.include?(key)

      self.class.new(@params.merge(TERM_KEY => set_params(FACET_TERMS.fetch(key))[TERM_KEY].to_s), actor: actor)
        .send(:facet_counts, key)
    end

    EXPORT_LIMIT = 1000

    def export_rows
      select_rows("#{union_sql} ORDER BY at DESC, id DESC LIMIT #{EXPORT_LIMIT}").map { |row| build_row(row) }
    end

    SUGGESTED = 12

    KNOWN_VERBS = <<~SQL.squish.freeze
      SELECT DISTINCT verb FROM fd.audit
      UNION
      SELECT DISTINCT action FROM slack.audit_event WHERE NOT ours
      UNION
      SELECT action FROM slack.audit_view_action
      ORDER BY verb
    SQL

    def known_verbs
      @known_verbs ||= ApplicationRecord.connection.select_values(KNOWN_VERBS)
    end

    private

    def facet_counts(key)
      from, upto = histogram_span
      return {} if from >= upto || selected_sources.empty?

      ApplicationRecord.transaction do
        ApplicationRecord.connection.execute(HISTOGRAM_TIMEOUT)
        result = select_rows(facet_sql(key), histogram_from: from, histogram_upto: upto).to_a
        key == "is" ? (result.first || {}).transform_values(&:to_i) : result.to_h { |row| [row["key"], row["event_count"].to_i] }
      end
    rescue ActiveRecord::QueryCanceled
      {}
    end

    def facet_sql(key)
      return ACTOR_TYPE_COUNTS.sub("UNION_SQL", union_sql(HISTOGRAM_WINDOW)) if key == "is"

      column = key == "network" ? format(NETWORK_ATTRIBUTE, field: "class", ip: ROW_IP) : "verb"
      <<~SQL
        SELECT #{column} AS key, count(*) AS event_count
        FROM (#{union_sql(HISTOGRAM_WINDOW)}) events
        WHERE #{key == "network" ? "events.ip IS NOT NULL" : "true"}
        GROUP BY 1
        ORDER BY event_count DESC
        LIMIT #{FACET_LIMIT}
      SQL
    end

    def network_filter? = search.of("network").any? || search.of("country").any?

    def network_clause(table)
      ip = "#{table}.ip"
      parts = []
      parts << "AND #{format(NETWORK_ATTRIBUTE, field: 'class', ip: ip)} IN (:networks)" if search.of("network").any?
      parts << "AND #{format(NETWORK_ATTRIBUTE, field: 'country', ip: ip)} IN (:countries)" if search.of("country").any?
      parts.join("\n").presence
    end

    def number_label(count) = ActiveSupport::NumberHelper.number_to_delimited(count)

    def since = Time.zone.at(0)

    def selected_sources
      return [] if identity_refused?

      sources = view ? VIEW_SOURCES.fetch(view) : SOURCES
      requested_sources = search.of("source")
      sources = sources & requested_sources.map { |source| source == "engine" ? FIRE_ENGINE : source } if requested_sources.any?
      sources.select { |source| may_see?(source) }
    end

    def refusals? = view == "refusals"

    ENGINE_BRANCH = <<~SQL.freeze
      SELECT 'fire_engine' AS source, a.id::text AS id, a.occurred_at AS at,
             a.actor_user_id AS actor_id, a.actor_kind AS actor_kind, a.verb AS verb,
             a.entity_type AS entity_kind, a.entity_id::text AS entity_id,
             a.entity_ref AS entity_ref, a.subject_user_id AS subject_id,
             a.before AS before, a.after AS after, NULL::jsonb AS detail,
             NULL::text AS ip, CASE WHEN a.entity_ref ~ '^[CGD][A-Z0-9]{2,}$' THEN a.entity_ref END AS channel,
             NULL::text AS app, NULL::text AS session
      FROM fd.audit a
      WHERE a.occurred_at >= :since AND (a.verb <> 'refused') = :non_refusals
        ENGINE_WHERE
    SQL

    SLACK_BRANCH = <<~SQL.freeze
      SELECT 'slack' AS source, e.id::text AS id, e.at AS at,
             e.actor_id AS actor_id, 'slack' AS actor_kind, e.action AS verb,
             e.entity_kind AS entity_kind, e.entity_id AS entity_id,
             NULL::text AS entity_ref, NULL::text AS subject_id,
             NULL::jsonb AS before, e.payload AS after, e.payload -> 'context' AS detail,
             host(e.ip) AS ip, e.channel_id AS channel, e.app_id AS app, e.session_id::text AS session
      FROM slack.audit_event e
      WHERE e.at >= :since AND NOT e.ours
        SLACK_WHERE
    SQL

    SLACK_VIEW_BRANCH = <<~SQL.freeze
      SELECT 'slack' AS source, v.id::text AS id, v.at AS at,
             v.actor_id AS actor_id, 'slack' AS actor_kind, a.action AS verb,
             a.entity_kind AS entity_kind, v.object_id AS entity_id,
             NULL::text AS entity_ref, NULL::text AS subject_id,
             NULL::jsonb AS before, NULL::jsonb AS after,
             jsonb_strip_nulls(jsonb_build_object('ip_address', host(v.ip), 'ua', u.ua,
               'session_id', v.session_id)) AS detail,
             host(v.ip) AS ip, CASE WHEN v.object_id ~ '^[CGD][A-Z0-9]{2,}$' THEN v.object_id END AS channel,
             NULL::text AS app, v.session_id::text AS session
      FROM slack.audit_view v
      JOIN slack.audit_view_action a ON a.code = v.action
      LEFT JOIN slack.user_agent u ON u.id = v.ua_id
      WHERE v.at >= :since AND NOT v.ours
        SLACK_VIEW_WHERE
    SQL

    SLACK_SEARCHED = <<~SQL.squish.freeze
      to_tsvector('simple'::regconfig,
        coalesce(action, '') || ' ' || coalesce(actor_id, '') || ' ' ||
        coalesce(entity_id, '') || ' ' || coalesce(entity_kind, '') || ' ' ||
        coalesce(host(ip), '') || ' ' || coalesce(payload #>> '{context,app,name}', '') || ' ' ||
        coalesce(actor_email, '') || ' ' || coalesce(payload #>> '{actor,user,name}', '') || ' ' ||
        coalesce(entity_email, '') || ' ' || coalesce(payload #>> '{entity,user,name}', '') || ' ' ||
        coalesce(payload #>> '{entity,channel,name}', ''))
    SQL

    SLACK_VIEW_SEARCHED = <<~SQL.squish.freeze
      to_tsvector('simple'::regconfig,
        a.action || ' ' || coalesce(v.actor_id, '') || ' ' || coalesce(v.object_id, '') || ' ' ||
        coalesce(host(v.ip), ''))
    SQL

    VIEW_ACTIONS = <<~SQL.squish.freeze
      SELECT action FROM slack.audit_view_action
    SQL

    READ_BRANCH = <<~SQL.freeze
      SELECT 'read' AS source, 'r' || l.id::text AS id, l.looked_at AS at,
             l.actor_id AS actor_id, 'human' AS actor_kind, 'read' AS verb,
             'identity' AS entity_kind, l.subject_user_id AS entity_id,
             NULL::text AS entity_ref, l.subject_user_id AS subject_id,
             NULL::jsonb AS before, NULL::jsonb AS after,
             jsonb_build_object('field_class', l.field_class) AS detail,
             NULL::text AS ip, NULL::text AS channel, NULL::text AS app, NULL::text AS session
      FROM app.access_log l
      WHERE l.looked_at >= :since
        READ_WHERE
    SQL

    API_EVENT_BRANCH = <<~SQL.freeze
      SELECT 'api' AS source, 'ae' || e.id::text AS id, e.at AS at,
             e.actor_user_id AS actor_id, 'human'::text AS actor_kind,
             'api/' || e.verb AS verb,
             'api'::text AS entity_kind, e.subject AS entity_id,
             NULL::text AS entity_ref, NULL::text AS subject_id,
             NULL::jsonb AS before, NULL::jsonb AS after,
             jsonb_strip_nulls(jsonb_build_object('note', e.detail)) AS detail,
             NULL::text AS ip, NULL::text AS channel, NULL::text AS app, NULL::text AS session
      FROM api.event_log e
      WHERE e.at >= :since
        API_EVENT_WHERE
    SQL

    API_CONSENT_BRANCH = <<~SQL.freeze
      SELECT 'api' AS source, 'ac' || c.id::text AS id, c.at AS at,
             c.user_id AS actor_id, 'human'::text AS actor_kind,
             'consent/' || c.state AS verb,
             'scope'::text AS entity_kind, c.capability AS entity_id,
             NULL::text AS entity_ref, c.user_id AS subject_id,
             NULL::jsonb AS before, NULL::jsonb AS after,
             jsonb_build_object('via', c.via) AS detail,
             NULL::text AS ip, NULL::text AS channel, NULL::text AS app, NULL::text AS session
      FROM api.consent_log c
      WHERE c.at >= :since
        API_CONSENT_WHERE
    SQL

    API_REQUEST_BRANCH = <<~SQL.freeze
      SELECT 'api' AS source, 'ar' || r.id::text AS id, r.at AS at,
             t.owner_user_id AS actor_id, 'app'::text AS actor_kind,
             'api/checked'::text AS verb,
             'channel'::text AS entity_kind, r.channel_id AS entity_id,
             r.channel_id AS entity_ref, r.subject_user_id AS subject_id,
             NULL::jsonb AS before, NULL::jsonb AS after,
             jsonb_build_object('outcome', r.outcome, 'token', t.prefix) AS detail,
             NULL::text AS ip, r.channel_id AS channel, NULL::text AS app, NULL::text AS session
      FROM api.request_log r
      JOIN api.token t ON t.id = r.token_id
      WHERE r.at >= :since
        API_REQUEST_WHERE
    SQL

    def api_where(at:, actor:, subject:, verb:, kind:, channel: nil)
      parts = []
      parts << "AND #{actor} IN (:actors)" if search.of("actor").any?
      parts << "AND #{subject} IN (:subjects)" if search.of("about").any?
      parts << "AND #{verb} IN (:actions)" if search.of("action").any?
      if search.of("channel").any?
        parts << (channel ? "AND #{channel} IN (:channels)" : "AND false")
      end
      parts << "AND false" if search.text?
      parts << "AND false" if search.of("ip").any? || network_filter?
      parts << "AND false" if search.of("app").any? || search.of("session").any?
      parts << "AND false" if search.of("category").any?
      if identity_lookup? && search.of("ip").empty?
        parts << (matched_user_ids.any? ? "AND (#{actor} IN (:matched_user_ids) OR " \
                                 "#{subject} IN (:matched_user_ids))" : "AND false")
      end
      parts << api_actor_type_clause(actor, kind)
      parts << "AND #{at} >= :after" if from_at
      parts << "AND #{at} < :before" if upto_at
      parts.compact.join("\n")
    end

    def api_actor_type_clause(actor, kind)
      case search.first_value("is")
      when "human" then kind == "human" ? nil : "AND false"
      when "nemo" then "AND false"
      when "nobody" then "AND #{actor} IS NULL"
      end
    end

    def api_event_where
      api_where(at: "e.at", actor: "e.actor_user_id", subject: "NULL::text",
        verb: "('api/' || e.verb)", kind: "human")
    end

    def api_consent_where
      api_where(at: "c.at", actor: "c.user_id", subject: "c.user_id",
        verb: "('consent/' || c.state)", kind: "human")
    end

    def api_request_where
      api_where(at: "r.at", actor: "t.owner_user_id", subject: "r.subject_user_id",
        verb: "'api/checked'", kind: "app", channel: "r.channel_id")
    end

    def matched_user_ids
      @matched_user_ids ||= (search.member_ids_for_email + search.member_ids_for_ip).uniq
    end

    def identity_lookup?
      search.of("email").any? || search.of("domain").any? || search.of("ip").any?
    end

    def no_identity_match? = identity_lookup? && matched_user_ids.empty? && search.of("ip").empty?

    def engine_where
      parts = []
      parts << "AND a.actor_user_id IN (:actors)" if search.of("actor").any?
      parts << "AND a.subject_user_id IN (:subjects)" if search.of("about").any?
      parts << "AND a.verb IN (:actions)" if search.of("action").any?
      parts << "AND a.entity_ref IN (:channels)" if search.of("channel").any?
      parts << "AND false" if search.of("app").any? || search.of("session").any?
      parts << "AND false" if search.of("category").any?
      parts << "AND a.searchable @@ websearch_to_tsquery('simple', :text)" if search.text?
      parts << "AND false" if search.of("ip").any? || network_filter?
      if identity_lookup? && search.of("ip").empty?
        parts << (matched_user_ids.any? ? "AND (a.subject_user_id IN (:matched_user_ids) OR " \
                                 "a.actor_user_id IN (:matched_user_ids))" : "AND false")
      end
      parts << actor_type_clause("a.actor_user_id", "a.actor_kind")
      parts << "AND a.occurred_at >= :after" if from_at
      parts << "AND a.occurred_at < :before" if upto_at
      parts.compact.join("\n")
    end

    def slack_where
      parts = []
      parts << "AND e.actor_id IN (:actors)" if search.of("actor").any?
      parts << "AND e.entity_id IN (:subjects)" if search.of("about").any?
      parts << "AND e.action IN (:actions)" if search.of("action").any?
      parts << "AND e.channel_id IN (:channels)" if search.of("channel").any?
      parts << "AND e.app_id IN (:apps)" if search.of("app").any?
      parts << "AND e.session_id IN (:sessions)" if search.of("session").any?
      parts << "AND e.category IN (:categories)" if search.of("category").any?
      parts << "AND #{SLACK_SEARCHED} @@ websearch_to_tsquery('simple', :text)" if search.text?
      parts << ip_clause("e") if search.of("ip").any?
      parts << network_clause("e") if network_filter?
      parts << email_clause if search.of("ip").empty? && identity_lookup?
      parts << "AND false" if search.first_value("is") == "nemo"
      parts << "AND e.at >= :after" if from_at
      parts << "AND e.at < :before" if upto_at
      parts.compact.join("\n")
    end

    def slack_view_where
      parts = []
      parts << "AND a.action IN (:actions)" if search.of("action").any?
      parts << "AND v.actor_id IN (:actors)" if search.of("actor").any?
      parts << "AND v.object_id IN (:subjects)" if search.of("about").any?
      parts << "AND v.object_id IN (:channels)" if search.of("channel").any?
      parts << "AND false" if search.of("app").any?
      parts << "AND v.session_id IN (:sessions)" if search.of("session").any?
      parts << "AND a.action IN (:category_actions)" if search.of("category").any?
      parts << "AND #{SLACK_VIEW_SEARCHED} @@ websearch_to_tsquery('simple', :text)" if search.text?
      parts << ip_clause("v") if search.of("ip").any?
      parts << network_clause("v") if network_filter?
      if identity_lookup? && search.of("ip").empty?
        parts << (matched_user_ids.any? ? "AND v.actor_id IN (:matched_user_ids)" : "AND false")
      end
      parts << "AND false" if search.first_value("is") == "nemo"
      parts << "AND v.at >= :after" if from_at
      parts << "AND v.at < :before" if upto_at
      parts.join("\n")
    end

    def view_actions
      @view_actions ||= ApplicationRecord.connection.select_values(VIEW_ACTIONS)
    end

    def high_volume? = search.first_value("show") == "high_volume"

    def slack_views? = high_volume? || search.of("action").intersect?(view_actions)

    EMAIL_FIELDS = %w[e.actor_email e.entity_email].freeze

    def email_clause
      conditions = []
      search.of("email").each_with_index do |_value, at|
        conditions.concat(EMAIL_FIELDS.map { |field| "#{field} = :email_#{at}" })
      end
      search.of("domain").each_with_index do |_value, at|
        conditions.concat(EMAIL_FIELDS.map { |field| "split_part(#{field}, '@', 2) = :domain_#{at}" })
      end
      conditions << "e.actor_id IN (:matched_user_ids)" if matched_user_ids.any?
      conditions.empty? ? "AND false" : "AND (#{conditions.join(' OR ')})"
    end

    def ip_clause(table)
      conditions = search.of("ip").map { |term_value|
        operator = term_value.include?("/") ? "<<" : "="
        "#{table}.ip #{operator} :ip_#{term_value.hash.abs}::inet"
      }
      actor_match = matched_user_ids.any? ? " OR #{table}.actor_id IN (:matched_user_ids)" : ""
      "AND ((#{conditions.join(' OR ')})#{actor_match})"
    end

    def actor_type_clause(actor_column, kind_column)
      case search.first_value("is")
      when "human" then "AND #{kind_column} = 'human' AND #{actor_column} IS NOT NULL"
      when "nemo" then "AND #{kind_column} <> 'human'"
      when "nobody" then "AND #{actor_column} IS NULL"
      end
    end

    def read_where
      parts = []
      parts << "AND l.actor_id IN (:actors)" if search.of("actor").any?
      parts << "AND l.subject_user_id IN (:subjects)" if search.of("about").any?
      parts << "AND false" if search.of("action").any? && search.of("action") != ["read"]
      parts << "AND false" if search.of("channel").any?
      parts << "AND false" if search.of("app").any? || search.of("session").any?
      parts << "AND false" if search.of("category").any?
      parts << "AND false" if search.text?
      parts << "AND false" if search.of("ip").any? || network_filter?
      if identity_lookup? && search.of("ip").empty?
        parts << (matched_user_ids.any? ? "AND (l.subject_user_id IN (:matched_user_ids) OR " \
                                 "l.actor_id IN (:matched_user_ids))" : "AND false")
      end
      parts << "AND false" if search.first_value("is") == "nemo"
      parts << "AND l.looked_at >= :after" if from_at
      parts << "AND l.looked_at < :before" if upto_at
      parts.compact.join("\n")
    end

    def branches
      selects = []
      if selected_sources.include?(FIRE_ENGINE)
        selects << ENGINE_BRANCH.sub("ENGINE_WHERE", engine_where)
      end
      if selected_sources.include?(SLACK)
        selects << SLACK_BRANCH.sub("SLACK_WHERE", slack_where)
        selects << SLACK_VIEW_BRANCH.sub("SLACK_VIEW_WHERE", slack_view_where) if slack_views?
      end
      selects << READ_BRANCH.sub("READ_WHERE", read_where) if selected_sources.include?(READ)
      if selected_sources.include?(API)
        selects << API_EVENT_BRANCH.sub("API_EVENT_WHERE", api_event_where)
        selects << API_CONSENT_BRANCH.sub("API_CONSENT_WHERE", api_consent_where)
        selects << API_REQUEST_BRANCH.sub("API_REQUEST_WHERE", api_request_where)
      end
      selects
    end

    EMPTY_BRANCH = <<~SQL.freeze
      SELECT NULL::text AS source, NULL::text AS id, NULL::timestamptz AS at,
             NULL::text AS actor_id, NULL::text AS actor_kind, NULL::text AS verb,
             NULL::text AS entity_kind, NULL::text AS entity_id, NULL::text AS entity_ref,
             NULL::text AS subject_id, NULL::jsonb AS before, NULL::jsonb AS after,
             NULL::jsonb AS detail, NULL::text AS ip, NULL::text AS channel, NULL::text AS app,
             NULL::text AS session
      WHERE false
    SQL

    COUNT_COLUMNS = "source".freeze

    def union_sql(where = "true", capped: false, columns: "*")
      selects = branches.presence || [EMPTY_BRANCH]
      if capped
        selects = selects.map { |branch| "(SELECT #{columns} FROM (#{branch}) branch LIMIT #{COUNT_CEILING + 1})" }
      end

      "WITH events AS (\n#{selects.join("\nUNION ALL\n")}\n) SELECT * FROM events WHERE #{where}"
    end

    def keyset
      return "true" if before_at.nil?

      "(at, id) < (:before_at::timestamptz, :before_id)"
    end

    AFTER_KEYSET = "(at, id) > (:after_at::timestamptz, :after_id)".freeze

    def paged_rows
      return select_rows(page_sql).map { |row| build_row(row) } if after_at.nil?

      result = select_rows("#{union_sql(AFTER_KEYSET)} ORDER BY at, id LIMIT #{LIMIT + 1}").map { |row| build_row(row) }
      return result.first(LIMIT).reverse if result.size > LIMIT

      @top = true
      select_rows("#{union_sql} ORDER BY at DESC, id DESC LIMIT #{LIMIT}").map { |row| build_row(row) }
    end

    def first_page?
      rows
      @top || (after_at.nil? && before_at.nil?)
    end

    def before_at
      return (jump_date + 1).in_time_zone.beginning_of_day if jump_date && @params["before_at"].blank?

      parse_timestamp(@params["before_at"])
    end

    def after_at
      return nil if @params["before_at"].present? || jump_date

      parse_timestamp(@params["after_at"])
    end

    def after_id = @params["after_id"].to_s.presence

    def parse_timestamp(value)
      text = value.to_s.presence
      text && Time.zone.parse(text)
    rescue ArgumentError
      nil
    end

    def before_id = @params["before_id"].to_s.presence

    def page_sql
      "#{union_sql(keyset)} ORDER BY at DESC, id DESC LIMIT #{LIMIT}"
    end

    def fetch_groups
      from, upto = histogram_span
      return [] if group.nil? || from >= upto || selected_sources.empty?

      result = ApplicationRecord.transaction do
        ApplicationRecord.connection.execute(HISTOGRAM_TIMEOUT)
        select_rows(group_sql, histogram_from: from, histogram_upto: upto).to_a
      end
      @group_total = result.first&.fetch("groups").to_i
      names = group == "app" ? app_names(result.filter_map { |row| row["sample"] }) : {}
      result.map do |row|
        Group.new(key: row["key"], count: row["event_count"].to_i, first_at: row["first_at"],
          last_at: row["last_at"], name: names[row["key"]])
      end
    rescue ActiveRecord::QueryCanceled
      @groups_slow = true
      []
    end

    def group_sql
      column = GROUP_COLUMNS.fetch(group)
      <<~SQL
        SELECT key, event_count, first_at, last_at, sample, count(*) OVER () AS groups
        FROM (
          SELECT #{column} AS key, count(*) AS event_count, min(at) AS first_at, max(at) AS last_at,
                 min(id) FILTER (WHERE source = 'slack') AS sample
          FROM (#{union_sql(HISTOGRAM_WINDOW)}) events
          WHERE #{column} IS NOT NULL
          GROUP BY 1
        ) grouped
        ORDER BY event_count DESC, key
        LIMIT #{GROUP_LIMIT}
      SQL
    end

    APP_NAMES = <<~SQL.squish.freeze
      SELECT app_id, payload #>> '{context,app,name}' AS name
      FROM slack.audit_event
      WHERE id IN (:ids) AND app_id IS NOT NULL
    SQL

    def app_names(ids)
      return {} if ids.empty?

      ApplicationRecord.connection.select_all(ApplicationRecord.sanitize_sql([APP_NAMES, { ids: ids }]))
        .to_h { |row| [row["app_id"], row["name"]] }
    end

    def histogram_sql
      "SELECT date_trunc(:unit, at AT TIME ZONE :zone)::text AS bin, count(*) AS event_count " \
        "FROM (#{union_sql(HISTOGRAM_WINDOW)}) events GROUP BY 1"
    end

    def count_sql
      capped = union_sql(capped: true, columns: COUNT_COLUMNS)
      "SELECT count(*) AS event_count FROM (#{capped} LIMIT #{COUNT_CEILING + 1}) capped_rows"
    end

    def binds
      values = {
        since: since, text: search.text, before_at: before_at, before_id: before_id,
        after_at: after_at, after_id: after_id,
        non_refusals: !refusals?,
        actors: search.of("actor").presence || [""],
        subjects: search.of("about").presence || [""],
        actions: search.of("action").presence || [""],
        channels: search.of("channel").presence || [""],
        apps: search.of("app").presence || [""],
        sessions: search.of("session").map(&:to_i).presence || [0],
        categories: search.of("category").presence || [""],
        category_actions: AuditCatalogue.actions_in(search.of("category")).presence || [""],
        matched_user_ids: matched_user_ids.presence || [""],
        networks: search.of("network").presence || [""],
        countries: search.of("country").presence || [""],
        after: from_at, before: upto_at
      }
      search.of("ip").each { |term_value| values[:"ip_#{term_value.hash.abs}"] = term_value }
      search.of("email").each_with_index { |term_value, at| values[:"email_#{at}"] = term_value.downcase }
      search.of("domain").each_with_index { |term_value, at| values[:"domain_#{at}"] = term_value.downcase }
      values
    end

    def parse_day(value)
      value && Time.zone.parse(value)
    end

    def from_at
      return @from_at if defined?(@from_at)

      @from_at = [parse_day(search.first_value("after")), search.since].compact.max
    end

    def upto_at
      return @upto_at if defined?(@upto_at)

      @upto_at = parse_day(search.first_value("before"))
    end

    def select_rows(sql, extra = {})
      ApplicationRecord.connection.select_all(ApplicationRecord.sanitize_sql([sql, binds.merge(extra)]))
    end

    COUNTS = <<~SQL.squish.freeze
      SELECT
        count(*) AS everything,
        count(*) FILTER (WHERE source = 'fire_engine') AS engine,
        count(*) FILTER (WHERE source = 'slack') AS slack,
        count(*) FILTER (WHERE source = 'read') AS reads,
        count(*) FILTER (WHERE source = 'api') AS api,
        0 AS refusals
      FROM events
    SQL

    def view_counts
      @view_counts ||= begin
        unfiltered = self.class.new(@params.except("view").merge("view" => NO_VIEW), actor: actor)
        row = ApplicationRecord.connection.select_one(
          ApplicationRecord.sanitize_sql([unfiltered.send(:counting_sql), unfiltered.send(:binds)])
        ) || {}
        VIEWS.keys.index_with { |key| row[key].to_i }
      end
    end

    def counting_sql
      capped = union_sql(capped: true, columns: COUNT_COLUMNS)
      "#{capped.sub(/SELECT \* FROM events WHERE true\z/, '')}#{COUNTS}"
    end

    def parse_json(value)
      return value if value.is_a?(Hash)
      return nil if value.blank?

      JSON.parse(value)
    rescue JSON::ParserError
      nil
    end

    def find_row(source, id)
      branch = case source
      when FIRE_ENGINE then ENGINE_BRANCH.sub("ENGINE_WHERE", "AND a.id::text = :id")
      when SLACK then "#{SLACK_BRANCH.sub('SLACK_WHERE', 'AND e.id::text = :id')}\n" \
                      "UNION ALL\n#{SLACK_VIEW_BRANCH.sub('SLACK_VIEW_WHERE', 'AND v.id::text = :id')}"
      when READ then READ_BRANCH.sub("READ_WHERE", "AND 'r' || l.id::text = :id")
      else api_branch_for(id)
      end
      row = ApplicationRecord.connection.select_all(
        ApplicationRecord.sanitize_sql([branch, binds.merge(id: id, since: Time.zone.at(0))])
      ).first
      row && build_row(row)
    end

    def api_branch_for(id)
      case id.to_s[0, 2]
      when "ae" then API_EVENT_BRANCH.sub("API_EVENT_WHERE", "AND 'ae' || e.id::text = :id")
      when "ac" then API_CONSENT_BRANCH.sub("API_CONSENT_WHERE", "AND 'ac' || c.id::text = :id")
      else API_REQUEST_BRANCH.sub("API_REQUEST_WHERE", "AND 'ar' || r.id::text = :id")
      end
    end

    def build_row(row)
      Row.new(
        source: row["source"], id: row["id"], at: row["at"], actor_id: row["actor_id"],
        actor_kind: row["actor_kind"], verb: row["verb"], entity_kind: row["entity_kind"],
        entity_id: row["entity_id"], entity_ref: row["entity_ref"],
        subject_id: row["subject_id"], before: visible(parse_json(row["before"])),
        after: visible(parse_json(row["after"])), detail: visible(parse_json(row["detail"])),
        channel: row["channel"], app: row["app"], session: row["session"],
        addressed: row["ip"].present?, address: (row["ip"] if identity?)
      )
    end

    IDENTITY_KEY = /email|ip_address/
    ADDRESS_SHAPE = /\A[0-9a-f.:]{3,45}\z/i
    HIDDEN = "hidden".freeze

    def visible(value)
      return value if identity?

      redacted(value)
    end

    def redacted(value)
      case value
      when Hash
        value.reject { |key, _| identity_key?(key, value) }.transform_values { |item| redacted(item) }
      when Array then value.map { |item| redacted(item) }
      when String then identity_value?(value) ? HIDDEN : value
      else value
      end
    end

    PERSON_NAMES = %w[name real_name display_name].freeze

    def identity_key?(key, hash)
      return true if key.to_s.match?(IDENTITY_KEY)

      PERSON_NAMES.include?(key.to_s) && hash["id"].to_s.match?(MEMBER_ID)
    end

    def identity_value?(value)
      return true if value.match?(AuditSearch::EMAIL)
      return false unless value.match?(ADDRESS_SHAPE)

      IPAddr.new(value)
      true
    rescue IPAddr::Error
      false
    end
  end
end

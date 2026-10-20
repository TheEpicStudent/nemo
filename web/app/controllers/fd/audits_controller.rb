module Fd
  class AuditsController < BaseController
    permit "case.read"

    def show
      @query = AuditQuery.new(params, actor: current_account)
      return redirect_to(fd_audit_path(@query.with_params(params[:add].to_s.strip))) if params[:add].present?

      if params[:start].present?
        return redirect_to(fd_audit_path(@query.range_params(params[:start], params[:end])
          .merge({ "explore" => params[:explore].presence }.compact)))
      end

      @groups = @query.group ? @query.groups : []
      @rows = @query.group ? [] : @query.rows
      @views = @query.views
      @saved = AuditSavedQuery.for(current_account)
      @open_event_url = open_event_url(params[:event])
      record_audit_reads(@query)
      @names = Names.for(member_ids_in(@rows) + group_keys("actor"))
      @channels = ChannelNames.for(channel_ids(@rows) + group_keys("channel"))
    end

    def rows
      @query = AuditQuery.new(params, actor: current_account)
      @groups = @query.group ? @query.groups : []
      @rows = @query.group ? [] : @query.rows
      record_audit_reads(@query)
      @names = Names.for(member_ids_in(@rows) + group_keys("actor"))
      @channels = ChannelNames.for(channel_ids(@rows) + group_keys("channel"))
      render layout: false
    end

    def facet
      @query = AuditQuery.new(params, actor: current_account)
      @facet = params[:facet].to_s
      return head :not_found unless AuditQuery::FACETS.include?(@facet)

      @counts = @query.facet(@facet)
      render layout: false
    end

    def export
      query = AuditQuery.new(params, actor: current_account)
      rows = query.export_rows
      record_audit_reads(query)
      AuditEntry.create!(
        actor_user_id: current_account.user_id, actor_kind: "human", entity_type: "audit_query",
        entity_id: 0, verb: "exported", source_app: Audit::SOURCE_APP, request_id: request.request_id,
        after: { "q" => query.term, "view" => query.view, "rows" => rows.size }
      )
      send_data audit_csv(rows), type: "text/csv", filename: "audit-#{Time.current.strftime('%Y%m%d-%H%M')}.csv"
    end

    def histogram
      @query = AuditQuery.new(params, actor: current_account)
      @days = @query.histogram
      render layout: false
    end

    def event
      @query_for_row = AuditQuery.new({}, actor: current_account)
      @row = AuditQuery.find_one(params[:source].to_s, params[:id].to_s, actor: current_account)
      return head :not_found if @row.nil?
      return head :forbidden unless @query_for_row.may_see?(@row.source)

      @context = AuditContext.new(@row, @query_for_row)
      related = @context.visible_related
      @names = Names.for([@row.actor_id, @row.subject_id, @row.entity_id].compact + member_ids_in(related))
      @channels = ChannelNames.for([@row.entity_ref, @row.entity_id, @row.channel].compact + channel_ids(related))
      render layout: turbo_frame_request? ? false : "application"
    end

    private

    def open_event_url(value)
      source, id = value.to_s.split(":", 2)
      fd_audit_event_path(source: source, id: id) if AuditQuery::SOURCES.include?(source) && id.present?
    end

    CSV_COLUMNS = %w[time source actor actor_kind event entity_kind entity target ip channel session].freeze

    CSV_QUOTED = /[",\r\n]/
    CSV_FORMULA = /\A[=+\-@]/

    def audit_csv(rows)
      lines = rows.map do |row|
        [row.at&.utc&.iso8601, row.source, row.actor_id, row.actor_kind, row.verb, row.entity_kind,
         row.entity_id, row.subject_id, row.ip, row.channel, row.session]
      end
      ([CSV_COLUMNS] + lines).map { |values| values.map { |value| csv_cell(value) }.join(",") }.join("\r\n")
    end

    def csv_cell(value)
      text = value.to_s
      text = "'#{text}" if text.match?(CSV_FORMULA)
      text.match?(CSV_QUOTED) ? %("#{text.gsub('"', '""')}") : text
    end

    def group_keys(kind)
      @query.group == kind ? @groups.map(&:key) : []
    end

    def member_ids_in(rows)
      rows.flat_map { |row| [row.actor_id, row.subject_id, member_entity_id(row)] }.compact
    end

    MEMBER_ID = /\A[UW][A-Z0-9]{2,}\z/

    def member_entity_id(row)
      row.entity_id if row.entity_id.to_s.match?(MEMBER_ID)
    end

    CHANNEL_ID = /\A[CGD][A-Z0-9]{2,}\z/

    def channel_ids(rows)
      rows.flat_map { |row| [row.entity_ref, row.entity_id, row.channel] }
        .select { |id| id.to_s.match?(CHANNEL_ID) }
    end
  end
end

module Fd
  class SearchesController < BaseController
    permit "case.read"
    ICONS = { "member" => "person", "case" => "case", "note" => "note",
              "report" => "report", "tag" => "tag" }.freeze

    PAGE_LIMIT = 20
    CLUSTER_LIMIT = 3
    AUDIT_WINDOW = "last:30d".freeze
    EMAIL_TERM = /\A[^@\s]+@[^@\s]+\.[a-z]+\z/i

    def show
      respond_to do |format|
        format.json { render json: payload }
        format.html { page }
      end
    end

    private

    def payload
      return command_payload if command_query?

      search = Search.new(params[:q], scope: params[:scope], actor: current_account)
      groups = search.searching? ? result_groups(search) : default_groups
      { term: search.term, scope: search.scope, groups: search.scope ? groups : with_extra_groups(groups, search) }
    end

    def with_extra_groups(groups, search)
      member_groups, other_groups = groups.partition { |group| group[:key] == "member" }
      [*member_groups, clusters_group(search), *other_groups, audit_group(search), pages_group(search.term)]
        .compact.reject { |group| group[:rows].empty? }
    end

    def clusters_group(search)
      return nil unless search.searching? && current_account.may?("member.links")

      clusters = MemberLink.clusters_for_members(search.matched_member_ids, limit: CLUSTER_LIMIT)
      names = Names.for(clusters.map(&:cluster_id))
      { key: "cluster", label: "Clusters", total: clusters.size,
        rows: clusters.map { |cluster| cluster_row(cluster, names) } }
    end

    def cluster_row(cluster, names)
      flags = [("ring" if cluster.ring), ("conflict" if cluster.conflict)].compact
      { kind: "cluster", svg: helpers.nav_icon("network").to_s, title: "#{names[cluster.cluster_id]} cluster",
        sub: [helpers.pluralize(cluster.accounts, "account"), *flags].join(" · "),
        url: fd_cluster_path(cluster.cluster_id) }
    end

    def audit_group(search)
      return nil unless search.searching? && audit_reader?

      token = audit_token(search.term)
      return nil if token.nil?

      audit_query = "#{token} #{AUDIT_WINDOW}"
      { key: "audit", label: "Audit log", total: 1,
        rows: [{ kind: "audit", svg: helpers.nav_icon("history").to_s, title: "Audit log: #{search.term}",
                 sub: audit_query, url: fd_audit_path(q: audit_query) }] }
    end

    def audit_reader?
      current_account.may?("access.read") || current_account.may?("audit.read")
    end

    def audit_token(term)
      return nil if term.match?(AuditSearch::IDENTITY_TEXT) && !current_account.may?("identity.read")
      return "ip:#{term}" if address?(term)
      return "email:#{term}" if term.match?(EMAIL_TERM)
      return term if AuditSearch::OPERATORS.key?(term.split(":", 2).first.downcase) && term.include?(":")

      term.include?(" ") ? %("#{term}") : term
    end

    def address?(term)
      IPAddr.new(term)
      true
    rescue IPAddr::Error
      false
    end

    def pages_group(term)
      query = term.to_s.downcase
      return nil if query.present? && query.length < Search::MIN_TERM

      stops = helpers.fd_nav_groups.flat_map { |_, group_stops| group_stops }
        .select { |stop| query.empty? || stop.label.downcase.split.any? { |word| word.start_with?(query) } }
      { key: "page", label: "Go to", total: stops.size,
        rows: stops.map { |stop| { kind: "page", svg: helpers.nav_icon(stop.icon).to_s, title: stop.label, url: stop.path } } }
    end

    def page
      started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      @search = Search.new(params[:q], scope: params[:scope], limit: PAGE_LIMIT,
        actor: current_account)
      @groups = @search.searching? ? result_groups(@search) : []
      @took = ((Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000).round
      @counts = group_counts
    end

    def group_counts
      unscoped_search = @search.scope ? Search.new(params[:q], limit: 1, actor: current_account) : @search
      return {} unless unscoped_search.searching?

      unscoped_search.groups.to_h { |group| [group.key, group.total] }
    end

    def command_query?
      params[:q].to_s.start_with?(">") || params[:scope] == "command"
    end

    def command_payload
      term = params[:q].to_s.delete_prefix(">").strip
      rows = commands.select { |row| term.blank? || row[:title].downcase.include?(term.downcase) }

      { term: term, scope: "command",
        groups: [{ key: "command", label: "Commands", total: rows.size, rows: gated(rows) }] }
    end

    def gated(rows)
      rows.map do |row|
        key = row.delete(:key)
        target = row.delete(:on)
        row.merge(why: key && Access.why_not(current_account, key, target))
      end
    end

    def commands
      case_commands + [
        { kind: "do", icon: "plus", title: "Open case", sub: nil, key: "case.open",
          url: fd_cases_path(open: "1") },
        { kind: "do", icon: "case", title: "Go to the cases", sub: nil, url: fd_cases_path },
        { kind: "do", icon: "person", title: "Go to the members", sub: nil, url: fd_members_path }
      ].compact
    end

    def case_commands
      kase = Case.find_by(id: params[:on_case])
      return [] if kase.nil?

      case_label = "on case #{kase.id}"
      [
        { kind: "do", icon: "resolve", title: "Resolve this case", sub: case_label,
          key: "case.resolve", on: kase, url: fd_case_path(kase, do: "resolve") },
        { kind: "do", icon: "action", title: "Log an action", sub: case_label,
          key: "case.act", on: kase, url: fd_case_path(kase, do: "action") },
        { kind: "do", icon: "note", title: "Add a note", sub: case_label,
          key: "case.note", url: fd_case_path(kase, do: "note") }
      ].compact
    end

    def result_groups(search)
      @names = Names.for(search.groups.flat_map { |group| named_in(group) })
      people = member_ids(search)
      @context = MemberContext.for(people)
      @priors = Case.prior_counts_for(people)
      @open = Case.open_counts_for(people)

      search.groups.map do |group|
        { key: group.key, label: group.label, total: group.total,
          rows: group.rows.map { |row| row_for(row) } }
      end
    end

    def default_groups
      [
        { key: "waiting", label: "Waiting on you", total: 1, rows: waiting },
        { key: "do", label: "Do", total: 1, rows: gated([
          { kind: "do", icon: "plus", title: "Open case", sub: nil, key: "case.open",
            url: fd_cases_path }
        ]) }
      ].reject { |group| group[:rows].empty? }
    end

    def waiting
      rows = []
      unassigned = Case.unresolved.unassigned.count
      if unassigned.positive?
        rows << { kind: "case", icon: "waiting", title: helpers.pluralize(unassigned, "unassigned case"),
                  sub: oldest_unassigned, url: fd_cases_path(view: "unassigned") }
      end

      rows
    end

    def oldest_unassigned
      oldest = Case.unresolved.unassigned.minimum(:opened_at)
      oldest && "oldest #{helpers.case_age_label(Time.current - oldest)}"
    end

    def named_in(group)
      group.rows.flat_map do |row|
        case row.record
        when Member then [row.record.user_id]
        when Case then row.record.subject_user_ids + row.record.assignee_user_ids
        when Note then [row.record.author]
        when CaseReport then [row.record.reporter_user_id]
        else []
        end
      end.compact
    end

    def member_ids(search)
      search.groups.flat_map { |group| group.rows.map(&:record) }
        .grep(Member).map(&:user_id)
    end

    def row_for(row)
      record = row.record
      {
        kind: row.kind,
        icon: ICONS.fetch(row.kind, "•"),
        title: title_for(record),
        sub: sub_for(record),
        snippet: row.snippet,
        url: url_for_record(record),
        id: (record.user_id if record.is_a?(Member)),
        initial: (@names.initial(record.user_id) if record.is_a?(Member))
      }
    end

    def title_for(record)
      case record
      when Member then @names[record.user_id]
      when Case then "case #{record.id}"
      when Note then record.case_id ? "case #{record.case_id}" : @names[record.subject_user_id]
      when CaseReport then "case #{record.case_id}"
      when Tag then record.name
      end
    end

    def sub_for(record)
      case record
      when Member then member_sub(record)
      when Case then case_sub(record)
      when Note then "#{@names[record.author]} · #{record.created_at.strftime('%-d %b')}"
      when CaseReport then report_sub(record)
      when Tag then helpers.pluralize(record.uses, "case")
      end
    end

    def member_sub(member)
      member_context = @context[member.user_id]
      parts = [member.user_id]
      parts << "@#{member.handle}" if member.handle.present? && "@#{member.handle}" != @names[member.user_id]
      parts << helpers.tenure_label(member_context&.tenure_days)
      parts << "#{helpers.number_with_delimiter(member_context.messages_posted)} messages" if
        member_context&.messages_posted
      priors = @priors.fetch(member.user_id, 0)
      parts << helpers.pluralize(priors, "prior") if priors.positive?
      open = @open.fetch(member.user_id, 0)
      parts << "#{open} open" if open.positive?
      parts.compact.join(" · ")
    end

    def case_sub(kase)
      parts = [helpers.category_label(kase.category_key).downcase]
      parts << if kase.resolved?
        helpers.resolution_label(kase.resolution).downcase
      else
        "open #{helpers.case_age_label(helpers.case_age_seconds(kase))}"
      end
      parts << @names.list(kase.assignee_user_ids) if kase.assigned?
      parts.join(" · ")
    end

    def report_sub(report)
      reporter_name = report.anonymous? ? "Anonymous" : @names[report.reporter_user_id]
      "#{reporter_name} · #{report.received_at.strftime('%-d %b')}"
    end

    def url_for_record(record)
      case record
      when Member then fd_member_path(record.user_id)
      when Case then fd_case_path(record)
      when Note then record.case_id ? fd_case_path(record.case_id) : fd_member_path(record.subject_user_id)
      when CaseReport then fd_case_path(record.case_id)
      when Tag then fd_cases_path(tag: record.name)
      end
    end
  end
end

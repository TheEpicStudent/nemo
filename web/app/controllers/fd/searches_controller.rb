module Fd
  class SearchesController < BaseController
    permit "case.read"
    ICONS = { "member" => "person", "case" => "case", "note" => "note",
              "report" => "report" }.freeze

    PAGE_LIMIT = 20
    CLUSTERS_SHOWN = 3
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
      return commanding if commanding?

      found = Search.new(params[:q], scope: params[:scope], actor: current_account)
      groups = found.asked? ? shown(found) : resting
      { term: found.term, scope: found.scope, groups: found.scope ? groups : widened(groups, found) }
    end

    def widened(groups, found)
      people, rest = groups.partition { |group| group[:key] == "member" }
      [*people, clusters_group(found), *rest, audit_group(found), pages_group(found.term)]
        .compact.reject { |group| group[:rows].empty? }
    end

    def clusters_group(found)
      return nil unless found.searching? && current_account.may?("member.links")

      clusters = MemberLink.clusters_of(found.matched_member_ids, limit: CLUSTERS_SHOWN)
      names = Names.for(clusters.map(&:cluster_id))
      { key: "cluster", label: "Clusters", total: clusters.size,
        rows: clusters.map { |one| cluster_row(one, names) } }
    end

    def cluster_row(cluster, names)
      flags = [("ring" if cluster.ring), ("conflict" if cluster.conflict)].compact
      { kind: "cluster", svg: helpers.nav_icon("network").to_s, title: "#{names[cluster.cluster_id]} cluster",
        sub: [helpers.pluralize(cluster.accounts, "account"), *flags].join(" · "),
        url: fd_cluster_path(cluster.cluster_id) }
    end

    def audit_group(found)
      return nil unless found.searching? && audit_reader?

      token = audit_token(found.term)
      return nil if token.nil?

      asked = "#{token} #{AUDIT_WINDOW}"
      { key: "audit", label: "Audit log", total: 1,
        rows: [{ kind: "audit", svg: helpers.nav_icon("history").to_s, title: "Audit log: #{found.term}",
                 sub: asked, url: fd_audit_path(q: asked) }] }
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
      wanted = term.to_s.downcase
      return nil if wanted.present? && wanted.length < Search::MIN_TERM

      stops = helpers.fd_nav_groups.flat_map { |_, held| held }
        .select { |stop| wanted.empty? || stop.label.downcase.split.any? { |word| word.start_with?(wanted) } }
      { key: "page", label: "Go to", total: stops.size,
        rows: stops.map { |stop| { kind: "page", svg: helpers.nav_icon(stop.icon).to_s, title: stop.label, url: stop.path } } }
    end

    def page
      started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      @found = Search.new(params[:q], scope: params[:scope], limit: PAGE_LIMIT,
        actor: current_account)
      @groups = @found.asked? ? shown(@found) : []
      @took = ((Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000).round
      @counts = every_count
    end

    def every_count
      whole = @found.scope ? Search.new(params[:q], limit: 1, actor: current_account) : @found
      return {} unless whole.asked?

      whole.groups.to_h { |group| [group.key, group.total] }
    end

    def commanding?
      params[:q].to_s.start_with?(">") || params[:scope] == "command"
    end

    def commanding
      term = params[:q].to_s.delete_prefix(">").strip
      rows = commands.select { |row| term.blank? || row[:title].downcase.include?(term.downcase) }

      { term: term, scope: "command",
        groups: [{ key: "command", label: "Commands", total: rows.size, rows: gated(rows) }] }
    end

    def gated(rows)
      rows.map do |row|
        key = row.delete(:key)
        on = row.delete(:on)
        row.merge(why: key && Access.why_not(current_account, key, on))
      end
    end

    def commands
      here + [
        { kind: "do", icon: "plus", title: "Open a case", sub: nil, key: "case.open",
          url: fd_cases_path(open: "1") },
        { kind: "do", icon: "case", title: "Go to the cases", sub: nil, url: fd_cases_path },
        { kind: "do", icon: "person", title: "Go to the members", sub: nil, url: fd_members_path }
      ].compact
    end

    def here
      kase = Case.find_by(id: params[:on_case])
      return [] if kase.nil?

      on = "on case #{kase.id}"
      [
        { kind: "do", icon: "resolve", title: "Resolve this case", sub: on,
          key: "case.resolve", on: kase, url: fd_case_path(kase, do: "resolve") },
        { kind: "do", icon: "action", title: "Log an action", sub: on,
          key: "case.act", on: kase, url: fd_case_path(kase, do: "action") },
        { kind: "do", icon: "note", title: "Add a note", sub: on,
          key: "case.note", url: fd_case_path(kase, do: "note") }
      ].compact
    end

    def shown(found)
      @names = Names.for(found.groups.flat_map { |group| named_in(group) })
      people = member_ids(found)
      @context = MemberContext.for(people)
      @priors = Case.prior_counts_for(people)
      @open = Case.open_counts_for(people)

      found.groups.map do |group|
        { key: group.key, label: group.label, total: group.total,
          rows: group.rows.map { |row| row_for(row) } }
      end
    end

    def resting
      [
        { key: "waiting", label: "Waiting on you", total: 1, rows: waiting },
        { key: "do", label: "Do", total: 1, rows: gated([
          { kind: "do", icon: "plus", title: "Open a case", sub: nil, key: "case.open",
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

    def member_ids(found)
      found.groups.flat_map { |group| group.rows.map(&:record) }
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
      end
    end

    def sub_for(record)
      case record
      when Member then member_sub(record)
      when Case then case_sub(record)
      when Note then "#{@names[record.author]} · #{record.created_at.strftime('%-d %b')}"
      when CaseReport then report_sub(record)
      end
    end

    def member_sub(member)
      seen = @context[member.user_id]
      parts = [member.user_id]
      parts << "@#{member.handle}" if member.handle.present? && "@#{member.handle}" != @names[member.user_id]
      parts << helpers.tenure_label(seen&.tenure_days)
      parts << "#{helpers.number_with_delimiter(seen.messages_posted)} messages" if
        seen&.messages_posted
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
      who = report.anonymous? ? "Anonymous" : @names[report.reporter_user_id]
      "#{who} · #{report.received_at.strftime('%-d %b')}"
    end

    def url_for_record(record)
      case record
      when Member then fd_member_path(record.user_id)
      when Case then fd_case_path(record)
      when Note then record.case_id ? fd_case_path(record.case_id) : fd_member_path(record.subject_user_id)
      when CaseReport then fd_case_path(record.case_id)
      end
    end
  end
end

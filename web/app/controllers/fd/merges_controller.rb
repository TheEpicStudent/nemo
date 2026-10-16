module Fd
  class MergesController < BaseController
    permit "case.resolve"

    PER_PAGE = 8

    def show
      @case = Case.find(params[:id])
      @term = params[:q].to_s.strip
      @page = [params[:page].to_i, 1].max
      @siblings = @case.sibling_cases.includes(:subjects).oldest_first.to_a
      @groups, @more = @term.present? ? [search_groups, false] : candidate_page
      @candidates = @groups.flat_map(&:last)
      read_reports(@candidates)
      @names = Names.for((@candidates + [@case])
        .flat_map(&:subject_user_ids) + [@case.opened_by] +
        @candidates.flat_map(&:assignee_user_ids) +
        @candidates.map(&:opened_by) +
        @candidates.flat_map { |kase| kase.reports.map(&:reporter_user_id) } +
        @cited_words.values.map(&:author))
      render "more", layout: false if @page > 1
    end

    def confirm
      ids = ticked_ids
      return redirect_with_alert("Select at least two cases to merge") if ids.size < 2

      @query_params = query_params
      cases = Case.where(id: ids).includes(:subjects, :assignees, :reports, :participants)
        .oldest_first.to_a
      return redirect_with_alert("Those cases no longer exist") if cases.size < 2

      @plan = MergePlan.over(cases, primary: params[:keep])
      @names = Names.for(cases.flat_map(&:subject_user_ids) +
        cases.flat_map(&:assignee_user_ids))
    end

    def create
      ids = ticked_ids
      return redirect_with_alert("Select the cases to mark as duplicates") if ids.empty?

      if params[:duplicate_of].present? && selected_target.nil?
        return redirect_with_alert("That case no longer exists")
      end
      if selected_target.nil? && ids.size < 2
        return redirect_with_alert("Select at least two cases: the oldest stays open, " \
          "the rest close as duplicates of it")
      end

      target = selected_target || oldest_of(ids)
      return redirect_with_alert("Those cases no longer exist") if target.nil?

      root = Case.root_for(target.id)
      marked = mark(ids - [root], root)

      if marked.zero?
        redirect_with_alert("Nothing to mark: those cases are already resolved")
      else
        redirect_to fd_cases_path(query_params), notice: outcome(marked, ids, root)
      end
    end

    private

    def ticked_ids
      Array(params[:case_ids]).map(&:to_i).reject(&:zero?).uniq
    end

    def candidate_page
      shared, subject, excluded_ids = Case.candidate_parts(@case, @siblings)
      around, more = Case.candidates_around(excluded_ids, page: @page, per: PER_PAGE)
      return [[[Case::AROUND, around]].reject { |_, cases| cases.empty? }, more] if @page > 1

      groups = [["same thread", shared],
                ["also about #{@case.subject_user_ids.any? ? 'the same person' : 'somebody on this case'}",
                 subject],
                [Case::AROUND, around]].reject { |_label, cases| cases.empty? }
      [groups, more]
    end

    def read_reports(cases)
      ActiveRecord::Associations::Preloader.new(records: cases,
        associations: [:reports, :assignees, { case_tags: :tag }]).call
      ids = cases.map(&:id)
      @attachment_counts = IntakeFile.counts_for_cases(ids)
      @cited_words = IntakeShare.first_shares_for(ids)
      @channels = ChannelNames.for(@cited_words.values.map(&:channel))
      @violations = Case.violations_for(ids)
      @priors = Case.prior_counts_for(cases.flat_map(&:subject_user_ids))
      @reachable = IntakeConversation.open
        .where(report_id: cases.flat_map { |kase| kase.reports.map(&:id) })
        .pluck(:report_id).to_set
    end

    def search_groups
      matches = Search.new(@term, scope: "case", limit: 8).groups
        .flat_map(&:rows).map(&:record)
        .reject { |kase| @case.family_ids.include?(kase.id) }
      matches.empty? ? [] : [["matching \"#{@term}\"", matches]]
    end

    def query_params
      params.permit(*CaseQuery::KEYS).to_h.compact_blank
    end

    def selected_target
      return nil if params[:duplicate_of].blank?

      @selected_target ||= Case.find_by(id: params[:duplicate_of])
    end

    def oldest_of(ids)
      Case.where(id: ids).order(:opened_at, :id).first
    end

    def mark(ids, root)
      now = Time.current
      marked = 0
      marked_ids = []

      writing do
        Case.where(id: ids).unresolved.order(:id).each do |kase|
          rows = Case.where(id: kase.id, resolved_at: nil)
            .update_all(
              resolved_at: now, resolution: "duplicate",
              duplicate_of: root, updated_at: now
            )
          next if rows.zero?

          marked += 1
          marked_ids << kase.id
          audit(kase.reload, "resolved",
            before: { "resolved_at" => nil, "resolution" => nil, "duplicate_of" => nil },
            after: {
              "resolved_at" => kase.resolved_at,
              "resolution" => "duplicate",
              "duplicate_of" => root
            })
        end
        carry_tags(marked_ids, root)
        carry_assignees(marked_ids, root)
      end

      marked
    end

    def carry_assignees(from_ids, root)
      return if from_ids.empty?

      Case.find(root).take_assignees_from!(from_ids, by: current_account.user_id).each do |assignee|
        audit(assignee, "attached", entity_id: root,
          after: { "user_id" => assignee.user_id, "carried_from" => from_ids })
      end
    end

    def carry_tags(from_ids, root)
      return if from_ids.empty?

      carried = Case.find(root).take_tags_from!(from_ids, by: current_account.user_id)
      return if carried.empty?

      audit(CaseTag.new(case_id: root), "added", entity_id: root,
        after: { "tags" => carried.map(&:name), "from" => from_ids })
    end

    def outcome(marked, ids, root)
      note = "#{marked} #{'case'.pluralize(marked)} closed as " \
        "#{'duplicate'.pluralize(marked)} of case #{root}, which stays open"
      skipped = ids.reject { |id| id == root }.size - marked
      skipped.positive? ? "#{note}, #{skipped} left alone" : note
    end

    def redirect_with_alert(message)
      redirect_to fd_cases_path(query_params), alert: message
    end
  end
end

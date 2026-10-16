module Fd
  class ResolutionsController < BaseController
    permit "case.resolve", on: -> { Case.find(params[:case_id]) }, only: :create
    permit "case.reopen", on: -> { Case.find(params[:case_id]) }, only: :destroy

    def create
      @case = Case.find(params[:case_id])
      @now = Time.current

      resolution = resolution_reason
      return redirect_with_alert("Enter why this case is closing") if resolution.nil?

      resolved = false
      writing do
        next unless mark_resolved(resolution)

        resolved = true
        close_reports if notify_reporter?
        @case.reload
        audit(@case, "resolved",
          before: { "resolved_at" => nil, "resolution" => nil },
          after: {
            "resolved_at" => @case.resolved_at,
            "resolution" => resolution,
            "duplicate_of" => @case.duplicate_of,
            "member_note" => @case.member_note
          })
      end

      if resolved
        redirect_to fd_case_path(@case), notice: "Case #{@case.id} resolved"
      else
        redirect_with_alert("Case #{@case.id} was already resolved")
      end
    end

    def destroy
      @case = Case.find(params[:case_id])
      @now = Time.current

      return redirect_with_alert("Case #{@case.id} is already open") unless @case.resolved?

      previous_state = { "resolved_at" => @case.resolved_at, "resolution" => @case.resolution,
                         "duplicate_of" => @case.duplicate_of }

      writing do
        @case.update!(resolved_at: nil, resolution: nil, duplicate_of: nil, updated_at: @now)
        reopen_reports
        audit(@case, "reopened", before: previous_state,
          after: { "resolved_at" => nil, "resolution" => nil, "duplicate_of" => nil })
      end

      redirect_to fd_case_path(@case), notice: "Case #{@case.id} reopened"
    end

    private

    def resolution_reason
      return "action_taken" if Action.where(case_id: @case.family_ids).live.any?

      reason = params[:close_reason].to_s
      Case::CLOSE_REASONS.include?(reason) ? reason : nil
    end

    def notify_reporter?
      params[:notify_reporter] == "1"
    end

    def reporter_message
      message = params[:member_message].to_s.strip
      message.presence || Resolution::DEFAULT_MESSAGE
    end

    def mark_resolved(resolution)
      Case.where(id: @case.id, resolved_at: nil)
        .update_all(
          resolved_at: @now,
          resolution: resolution,
          member_note: params[:member_note].presence,
          updated_at: @now
        ).positive?
    end

    def close_reports
      message = reporter_message

      CaseReport.where(case_id: @case.family_ids, closed_at: nil).find_each do |report|
        report.update!(closed_at: @now, closed_by: current_account.user_id)
        audit(report, "closed", entity_id: @case.id,
          before: { "closed_at" => nil }, after: { "closed_at" => @now })
        queue(report, message)
      end
    end

    def reopen_reports
      CaseReport.where(case_id: @case.family_ids).where.not(closed_at: nil).find_each do |report|
        previous_closure = { "closed_at" => report.closed_at, "closed_by" => report.closed_by }
        report.update!(closed_at: nil, closed_by: nil)
        audit(report, "reopened", entity_id: @case.id,
          before: previous_closure, after: { "closed_at" => nil, "closed_by" => nil })
      end
    end

    def queue(report, message)
      conversation = IntakeConversation.find_by(report_id: report.id, closed_at: nil)
      return if conversation.nil?

      IntakeOutbox.create!(conversation_id: conversation.id, kind: "outcome", body: message,
        requested_by: current_account.user_id)
    end

    def redirect_with_alert(message)
      redirect_to fd_case_path(@case), alert: message
    end
  end
end

module Fd
  module ClosesReports
    private

    def notify_reporter?
      params[:notify_reporter] == "1"
    end

    def reporter_message
      message = params[:member_message].to_s.strip
      message.presence || Resolution::DEFAULT_MESSAGE
    end

    def close_reports(kase, at)
      message = reporter_message

      CaseReport.where(case_id: kase.family_ids, closed_at: nil).find_each do |report|
        report.update!(closed_at: at, closed_by: current_account.user_id)
        audit(report, "closed", entity_id: kase.id,
          before: { "closed_at" => nil }, after: { "closed_at" => at })
        queue_outcome(report, message)
      end
    end

    def queue_outcome(report, message)
      conversation = IntakeConversation.find_by(report_id: report.id, closed_at: nil)
      return if conversation.nil?

      IntakeOutbox.create!(conversation_id: conversation.id, kind: "outcome", body: message,
        requested_by: current_account.user_id)
    end
  end
end

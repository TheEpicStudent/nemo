module Fd
  class RepliesController < BaseController
    permit "case.reply", on: -> { Case.find(params[:case_id]) }

    def create
      kase = Case.find(params[:case_id])
      parsed = Marks.read(params[:body], to_reporter: true)
      sent = nil

      writing do
        sent = Outgoing.queue(conversation_for(kase), parsed.body, mode: mode(parsed),
          by: current_account.user_id, asked: params[:conversation_id].present?)
        answered(kase, sent.queued) if sent.queued
      end

      return redirect_to(back_to(kase), alert: sent.problem) if sent.problem

      respond_to do |format|
        format.turbo_stream { render turbo_stream: CaseChatBroadcast.tag(kase.id) }
        format.html do
          flash[:detail] = "It goes out as a DM. Your name is on it either way."
          redirect_to back_to(kase), notice: "Reply queued for the reporter"
        end
      end
    end

    private

    def conversation_for(kase)
      conversations = IntakeConversation.for_case(kase.family_ids).open
      return conversations.first if params[:conversation_id].blank?

      conversations.find_by(id: params[:conversation_id])
    end

    def answered(kase, queued)
      audit(queued.conversation.report, "answered", entity_id: kase.id,
        after: { "outbox_id" => queued.id, "mode" => queued.mode })
    end

    def back_to(kase)
      fd_case_path(kase, tab: "report")
    end

    def mode(parsed)
      parsed.signed? && params[:anon] != "1" ? "signed" : "body"
    end
  end
end

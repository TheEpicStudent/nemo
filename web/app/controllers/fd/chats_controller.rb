module Fd
  class ChatsController < BaseController
    permit "case.chat", on: -> { Case.find(params[:case_id]) }

    def create
      kase = Case.find(params[:case_id])
      parsed = Marks.read(Mentions.normalise(params[:body].to_s.strip))

      return send_to_reporter(kase, parsed) if parsed.to_reporter?

      error = validation_error(parsed.body)
      return redirect_to(back_to(kase), alert: error) if error

      line = writing { create_chat_line(kase, parsed.body) }
      SlackPost.post_to_thread(line) if line.mirrored_as == "user"

      answer(kase)
    end

    private

    def conversation_for(kase)
      conversations = IntakeConversation.for_case(kase.family_ids).open
      return conversations.first if params[:conversation_id].blank?

      conversations.find_by(id: params[:conversation_id])
    end

    def send_to_reporter(kase, parsed)
      denied_reason = Access.why_not(current_account, "case.reply", kase)
      return redirect_to(back_to(kase), alert: denied_reason) if denied_reason

      sent = nil
      writing do
        sent = Outgoing.queue(conversation_for(kase), parsed.body, mode: mode(parsed),
          by: current_account.user_id, asked: params[:conversation_id].present?)
        answered(kase, sent.queued) if sent.queued
      end

      return redirect_to(back_to(kase), alert: sent.problem) if sent.problem

      answer(kase)
    end

    def answered(kase, queued)
      audit(queued.conversation.report, "answered", entity_id: kase.id,
        after: { "outbox_id" => queued.id, "mode" => queued.mode })
    end

    def mode(parsed)
      parsed.signed? && params[:anon] != "1" ? "signed" : "body"
    end

    def create_chat_line(kase, body)
      CaseChat.create!(
        case_id: kase.id,
        author_user_id: current_account.user_id,
        body: body,
        source_app: Audit::SOURCE_APP,
        mirrored_as: (SlackPost.claimable?(kase.id, current_account.user_id) ? "user" : nil)
      )
    end

    def answer(kase)
      respond_to do |format|
        format.turbo_stream { render turbo_stream: CaseChatBroadcast.tag(kase.id) }
        format.html { redirect_to back_to(kase) }
      end
    end

    def back_to(kase)
      fd_case_path(kase, tab: "report")
    end

    def validation_error(body)
      return "write something first" if body.blank?
      return "that is too long, keep it under #{CaseChat::MAX_LENGTH}" if
        body.length > CaseChat::MAX_LENGTH

      nil
    end
  end
end

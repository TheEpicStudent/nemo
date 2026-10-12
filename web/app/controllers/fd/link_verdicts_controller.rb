module Fd
  class LinkVerdictsController < BaseController
    permit "link.verdict"

    MEMBER_ID = /\A[UW][A-Z0-9]{2,}\z/
    NOTICES = { recorded: "verdict recorded", changed: "verdict changed", unchanged: "verdict unchanged" }.freeze

    def create
      error = validation_error
      return redirect_to(back, alert: error) if error

      outcome = nil
      writing { outcome = record }
      redirect_to back, notice: NOTICES.fetch(outcome)
    end

    private

    def pair = LinkVerdict.pair(params[:a].to_s.strip.upcase, params[:b].to_s.strip.upcase)

    def verdict = params[:verdict].to_s

    def note = params[:note].to_s.strip.presence

    def validation_error
      a, b = pair
      return "pick two accounts" unless a.match?(MEMBER_ID) && b.match?(MEMBER_ID) && a != b
      return "pick a verdict" unless LinkVerdict::VERDICTS.key?(verdict)

      nil
    end

    def record
      a, b = pair
      existing = LinkVerdict.lock.find_by(a_user_id: a, b_user_id: b)
      effective_note = note || existing&.note
      return :unchanged if existing && existing.verdict == verdict && existing.note == effective_note

      before = existing&.audit_attributes
      row = existing || LinkVerdict.new(a_user_id: a, b_user_id: b)
      row.update!(verdict: verdict, decided_by: current_account.user_id, decided_at: Time.current, note: effective_note)
      audit(row, row.verb, before: before, after: row.audit_attributes.merge("a_user_id" => a, "b_user_id" => b),
        subject_user_id: b)
      existing ? :changed : :recorded
    end

    def back
      requested_path = params[:back].to_s
      requested_path.start_with?("/fd/") ? requested_path : fd_links_path
    end
  end
end

module Fd
  class ParticipantsController < BaseController
    MEMBER_ID = /\A[UW][A-Z0-9]{2,}\z/
    SUBJECT = "subject".freeze

    permit "case.people", on: -> { Case.find(params[:case_id]) }

    def create
      kase = Case.find(params[:case_id])
      user_ids = requested_user_ids

      error = validation_error(user_ids)
      return redirect_to(fd_case_path(kase, tab: "people"), alert: error) if error

      added = []
      already_added = []

      writing do
        user_ids.each do |user_id|
          ActiveRecord::Base.transaction(requires_new: true) do
            person = kase.participants.create!(user_id: user_id, role: SUBJECT)
            audit(person, "attached", entity_id: kase.id)
          end
          added << user_id
        rescue ActiveRecord::RecordNotUnique
          already_added << user_id
        end
      end

      redirect_to fd_case_path(kase, tab: "people"), notice: added_notice(added, already_added)
    end

    def destroy
      kase = Case.find(params[:case_id])
      person = CaseParticipant.where(case_id: kase.family_ids)
        .find_by(user_id: params[:id], role: params[:role])

      if person.nil?
        return redirect_to(fd_case_path(kase, tab: "people"), alert: "They are not on this case")
      end

      writing do
        audit(person, "detached", entity_id: kase.id,
          before: { "user_id" => person.user_id, "role" => person.role },
          after: nil)
        person.destroy!
      end

      redirect_to fd_case_path(kase, tab: "people"),
        notice: "@#{person.user_id} removed from the case"
    end

    private

    def requested_user_ids
      raw = params[:user_ids].presence || [params[:user_id]]
      Array(raw).map { |id| id.to_s.strip.delete_prefix("@").upcase }.reject(&:blank?).uniq
    end

    def validation_error(user_ids)
      return "say who to add" if user_ids.empty?
      return nil if user_ids.all? { |id| id.match?(MEMBER_ID) }

      "that does not look like a Slack member id"
    end

    def added_notice(added, already_added)
      return "everybody you picked was already on this case, nothing changed" if added.empty?

      mentions = added.map { |id| "@#{id}" }.to_sentence
      note = "the case is now also about #{mentions}"
      already_added.any? ? "#{note}, #{already_added.size} already there" : note
    end
  end
end

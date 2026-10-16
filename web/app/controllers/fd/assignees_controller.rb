module Fd
  class AssigneesController < BaseController
    MEMBER_ID = /\A[UW][A-Z0-9]{2,}\z/

    permit "case.open", on: -> { Case.find(params[:case_id]) }

    def create
      kase = Case.find(params[:case_id])
      user_ids = requested_user_ids

      error = validation_error(kase, user_ids)
      return redirect_to(fd_case_path(kase), alert: error) if error

      added = []
      already_assigned = []

      writing do
        user_ids.each do |user_id|
          ActiveRecord::Base.transaction(requires_new: true) do
            assignee = kase.assign!(user_id, by: current_account.user_id)
            audit(assignee, "attached", entity_id: kase.id)
          end
          added << user_id
        rescue ActiveRecord::RecordNotUnique
          already_assigned << user_id
        end
      end

      redirect_to fd_case_path(kase), notice: assigned_notice(added, already_assigned)
    end

    def destroy
      kase = Case.find(params[:case_id])
      assignee = kase.assignees.find_by(user_id: params[:id])

      if assignee.nil?
        return redirect_to(fd_case_path(kase), alert: "Not assigned")
      end

      writing do
        audit(assignee, "detached", entity_id: kase.id,
          before: { "user_id" => assignee.user_id, "assigned_by" => assignee.assigned_by },
          after: nil)
        assignee.destroy!
      end

      redirect_to fd_case_path(kase), notice: "@#{assignee.user_id} removed from the case"
    end

    private

    def requested_user_ids
      raw = params[:user_ids].presence || [params[:user_id]]
      Array(raw).map { |id| id.to_s.strip.delete_prefix("@").upcase }.reject(&:blank?).uniq
    end

    def validation_error(kase, user_ids)
      return "Select a member" if user_ids.empty?
      unless user_ids.all? { |id| id.match?(MEMBER_ID) }
        return "Not a Slack member ID"
      end
      return "Case #{kase.id} is already resolved" if kase.resolved?

      nil
    end

    def assigned_notice(added, already_assigned)
      return "Already assigned" if added.empty?

      mentions = added.map { |id| "@#{id}" }.to_sentence
      note = "#{mentions} assigned"
      already_assigned.any? ? "#{note} · #{already_assigned.size} already assigned" : note
    end
  end
end

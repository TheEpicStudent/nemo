module Fd
  class ClaimsController < BaseController
    permit "case.open", on: -> { Case.find(params[:case_id]) }

    def create
      kase = Case.find(params[:case_id])
      claimed = false

      writing do
        locked = Case.lock.find(kase.id)
        next if locked.resolved? || locked.assigned_to?(current_account.user_id)

        claimed = true
        audit(locked.assign!(current_account.user_id), "claimed", entity_id: locked.id)
      end

      if claimed
        redirect_to fd_case_path(kase), notice: claim_notice(kase.reload)
      else
        redirect_to fd_case_path(kase), alert: claim_refusal(kase.reload)
      end
    end

    def destroy
      kase = Case.find(params[:case_id])
      assignment = kase.assignees.find_by(user_id: current_account.user_id)

      return redirect_to(fd_case_path(kase), alert: release_refusal(kase)) if assignment.nil?

      writing do
        audit(assignment, "unclaimed", entity_id: kase.id,
          before: { "user_id" => assignment.user_id, "assigned_by" => assignment.assigned_by },
          after: nil)
        assignment.destroy!
      end

      redirect_to fd_case_path(kase), notice: release_notice(kase.reload)
    end

    private

    def claim_notice(kase)
      others = kase.assignee_user_ids - [current_account.user_id]
      return "case #{kase.id} is yours" if others.empty?

      "case #{kase.id} is yours, alongside #{others.map { |id| "@#{id}" }.to_sentence}"
    end

    def claim_refusal(kase)
      return "case #{kase.id} is already resolved" if kase.resolved?

      "case #{kase.id} is already yours"
    end

    def release_notice(kase)
      return "case #{kase.id} is back in the queue" unless kase.assigned?

      "case #{kase.id} is off your list, still with #{kase.assignee_handles}"
    end

    def release_refusal(kase)
      return "case #{kase.id} is not assigned to anybody" unless kase.assigned?

      "case #{kase.id} is assigned to #{kase.assignee_handles}, not to you"
    end
  end
end

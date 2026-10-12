module Fd
  class BulkDeactivationsController < BaseController
    permit "member.deactivate"

    MEMBER_ID = /\A[UW][A-Z0-9]{2,}\z/
    MAX_ACCOUNTS = 100
    NO_REASON = "deactivated in bulk from the new members page".freeze

    def create
      error = validation_error
      return redirect_with_alert(error) if error

      opened = 0
      writing do
        opened = requested_ids.count { |user_id| open_guard(user_id) }
      end

      redirect_to return_path, notice: notice_for(opened)
    end

    private

    def requested_ids
      @requested_ids ||= Array(params[:user_ids]).map { |user_id| user_id.to_s.strip.upcase }
        .select { |user_id| user_id.match?(MEMBER_ID) }.uniq
    end

    def reason = params[:reason].to_s.strip.presence || NO_REASON

    def cluster_id
      requested_id = params[:cluster_id].to_s.strip.upcase
      requested_id if requested_id.match?(MEMBER_ID)
    end

    def return_path
      return fd_cluster_path(cluster_id) if cluster_id

      fd_new_members_path(params.permit(*NewMemberQuery::KEYS).to_h.compact_blank)
    end

    def validation_error
      return "pick who this is about" if requested_ids.empty?
      return "that is more than #{MAX_ACCOUNTS} accounts at once" if requested_ids.size > MAX_ACCOUNTS

      nil
    end

    def open_guard(user_id)
      guard = MemberGuard.open!(kind: MemberGuard::DEACTIVATION, subject_id: user_id,
        by: current_account.user_id, reason: reason)
      return false if guard.nil?

      audit(guard, "opened")
      true
    end

    def notice_for(opened)
      summary = "#{helpers.pluralize(opened, 'account')} sent to nemo to deactivate"
      return summary if opened == requested_ids.size

      "#{summary}, #{requested_ids.size - opened} already had one standing"
    end

    def redirect_with_alert(message)
      redirect_to return_path, alert: (message unless flash[:field_error])
    end
  end
end

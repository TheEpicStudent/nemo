module Admin
  class RoleChannelsController < BaseController
    SHARED_ROLE = "gardener".freeze
    SHARED_ROLES = %w[gardener].freeze

    def show
      @role = selected_role
      @channels = Channels::Audience::Grant.live.where(role: @role).to_a
      @channels_by_id = Analytics::DimChannel.where(channel_id: @channels.map(&:channel_id))
        .index_by(&:channel_id)
      @role_user_ids = ApplicationRecord.connection.select_values(
        ApplicationRecord.sanitize_sql([
          "SELECT DISTINCT user_id FROM app.effective_role WHERE role = ? ORDER BY user_id", @role
        ])
      )
      @holders = @role_user_ids.size
      @names = Fd::Names.for(@channels.map(&:granted_by) + @role_user_ids)
    end

    def create
      return redirect_with_alert unless may_grant?

      channel_id = params[:channel_id].to_s
      return redirect_with_alert("Select a channel") if channel_id.blank?
      unless Analytics::DimChannel.where(channel_id: channel_id, archived: false).exists?
        return redirect_with_alert("#{channel_id} is not a channel")
      end

      Channels::Audience::Grant.create!(role: selected_role, channel_id: channel_id,
        granted_by: current_account.user_id, granted_at: Time.current)
      redirect_to back_to,
        notice: "##{channel_id} added"
    rescue ActiveRecord::RecordNotUnique
      redirect_with_alert("Channel already added")
    end

    def destroy
      return redirect_with_alert unless may_grant?

      Channels::Audience::Grant.live.where(role: selected_role, channel_id: params[:channel_id])
        .find_each { |grant| grant.update!(revoked_by: current_account.user_id,
                                          revoked_at: Time.current) }
      redirect_to back_to, notice: "##{params[:channel_id]} removed"
    end

    private

    def selected_role
      requested = params[:role].to_s
      SHARED_ROLES.include?(requested) ? requested : SHARED_ROLE
    end

    def back_to
      return admin_channels_path(q: params[:q].presence) if params[:from] == "channels"

      admin_role_channels_path(role: selected_role)
    end

    def redirect_with_alert(message = nil)
      redirect_to back_to,
        alert: message || Community::Access.why_not(current_account, "analytics.grant")
    end
  end
end

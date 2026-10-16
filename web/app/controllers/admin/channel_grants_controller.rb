module Admin
  class ChannelGrantsController < BaseController
    def create
      return redirect_with_alert unless may_grant?

      channel_id = params[:channel_id].to_s
      return redirect_with_alert("Select a channel") if channel_id.blank?
      return redirect_with_alert("#{channel_id} is not a channel") unless active_channel?(channel_id)

      ActiveRecord::Base.transaction do
        grant = Channels::Audience::Grant.create!(user_id: person_user_id, channel_id: channel_id,
          granted_by: current_account.user_id, granted_at: Time.current,
          reason: params[:reason].presence)
        Account.find_or_create_by!(user_id: person_user_id)
        audit(grant, "granted", entity_id: channel_id,
          after: { "user_id" => person_user_id, "channel_id" => channel_id })
      end
      Current.forget_roles

      redirect_to admin_person_path(person_user_id), notice: "Access to ##{channel_id} granted"
    rescue ActiveRecord::RecordNotUnique
      redirect_with_alert("Already granted")
    end

    def destroy
      return redirect_with_alert unless may_grant?

      Channels::Audience::Grant.live.where(user_id: person_user_id, channel_id: params[:channel_id])
        .find_each { |grant| revoke(grant) }
      redirect_to admin_person_path(person_user_id), notice: "Access to ##{params[:channel_id]} revoked"
    end

    private

    def revoke(grant)
      ActiveRecord::Base.transaction do
        grant.update!(revoked_by: current_account.user_id, revoked_at: Time.current)
        audit(grant, "revoked", entity_id: grant.channel_id,
          before: { "user_id" => grant.user_id, "channel_id" => grant.channel_id },
          after: { "user_id" => grant.user_id, "channel_id" => grant.channel_id,
                   "revoked_by" => current_account.user_id })
      end
    end

    def person_user_id
      params[:person_user_id].to_s.upcase
    end

    def active_channel?(channel_id)
      Analytics::DimChannel.where(channel_id: channel_id, archived: false).exists?
    end

    def redirect_with_alert(message = nil)
      redirect_to admin_person_path(person_user_id),
        alert: message || Community::Access.why_not(current_account, "analytics.grant")
    end
  end
end

module Admin
  class GrantsController < BaseController
    def create
      user_id = requested_user_id
      return redirect_with_alert("Select a member") if user_id.blank?
      return redirect_with_alert("#{user_id} is not a Slack user id") unless user_id.match?(PeopleSearch::MEMBER_ID)
      return redirect_with_alert(Community::Access.why_not(current_account, "analytics.grant")) unless may_grant?
      return redirect_with_alert("Cannot revoke own access") if self_demotion?(user_id)

      changed = ActiveRecord::Base.transaction { apply_grant_changes(user_id) }
      return redirect_to(admin_person_path(user_id), notice: "Nothing changed") if changed.zero?

      redirect_to admin_person_path(user_id), notice: "#{changed} change(s) saved"
    rescue Authz::Grant::NotAllowedError => e
      redirect_with_alert(e.message)
    end

    def destroy
      return redirect_with_alert(Community::Access.why_not(current_account, "analytics.grant")) unless may_grant?

      user_id = params[:id].to_s.strip.upcase
      return redirect_with_alert("#{user_id} is not a Slack user id") unless user_id.match?(PeopleSearch::MEMBER_ID)
      if user_id == current_account.user_id
        return redirect_with_alert("Cannot revoke own access")
      end

      ActiveRecord::Base.transaction { revoke_all(user_id) }
      redirect_to admin_people_path, notice: "Access revoked"
    end

    private

    def self_demotion?(user_id)
      return false unless user_id == current_account.user_id
      return false unless Fd::Access.manager?(current_account)

      params[:role].to_s != Fd::Access::MANAGER_ROLE
    end

    def apply_grant_changes(user_id)
      Account.find_or_create_by!(user_id: user_id)
      changed = grant_role(user_id) + sync_scopes(user_id) + grant_channels(user_id)
      Current.forget_roles
      changed
    end

    def revoke_all(user_id)
      Authz::Grant.live.for_person(user_id).find_each do |row|
        row.revoke!(by: current_account.user_id)
        audit(row, "revoked", after: { "user_id" => user_id, row.kind => row.name })
      end
      Channels::Audience::Grant.live.where(user_id: user_id).find_each do |row|
        row.update!(revoked_by: current_account.user_id, revoked_at: Time.current)
      end
      Current.forget_roles
    end

    def sole_role?(user_id, role)
      Authz::Grant.live.for_person(user_id).roles.pluck(:name) == [role]
    end

    def role_unchanged?(user_id, role)
      return Authz.effective_roles(user_id).empty? if role.blank?

      sole_role?(user_id, role)
    end

    def grant_role(user_id)
      role = params[:role].to_s
      return 0 if role_unchanged?(user_id, role)

      if role.present?
        Authz::Grant.grant!(user_id, kind: "role", name: role,
          by: current_account.user_id, reason: params[:reason].presence)
        audit_grant(user_id, "role", role, "granted")
      else
        Authz::Grant.live.for_person(user_id).roles.find_each do |row|
          row.revoke!(by: current_account.user_id)
          audit_grant(user_id, "role", row.name, "revoked")
        end
      end
      1
    end

    def sync_scopes(user_id)
      requested = Array(params[:scopes]).map(&:to_s).select { |key| Authz.keys.include?(key) }
      requested.reject! { |key| Authz.locked?(key) }
      granted = Authz::Grant.live.for_person(user_id).capabilities.where(effect: "allow")
        .pluck(:name)

      grant_added_scopes(user_id, requested - granted) + revoke_removed_scopes(user_id, granted - requested)
    end

    def grant_added_scopes(user_id, keys)
      keys.count do |key|
        Authz::Grant.grant!(user_id, kind: "capability", name: key,
          by: current_account.user_id, reason: params[:reason].presence)
        audit_grant(user_id, "capability", key, "granted")
        true
      end
    end

    def revoke_removed_scopes(user_id, keys)
      return 0 if params[:scopes_settled].blank?

      Authz::Grant.live.for_person(user_id).capabilities.where(effect: "allow", name: keys)
        .count do |row|
          row.revoke!(by: current_account.user_id)
          audit(row, "revoked", after: { "user_id" => user_id, "capability" => row.name })
          true
        end
    end

    def grant_channels(user_id)
      requested_ids = Array(params[:channels]).map(&:to_s).reject(&:blank?)
      channel_ids = Analytics::DimChannel.where(channel_id: requested_ids, archived: false).pluck(:channel_id)
      return 0 if channel_ids.empty?

      channel_ids.each do |channel_id|
        next if Channels::Audience::Grant.live
          .where(user_id: user_id, channel_id: channel_id).exists?

        Channels::Audience::Grant.create!(user_id: user_id, channel_id: channel_id,
          granted_by: current_account.user_id, granted_at: Time.current,
          reason: params[:reason].presence)
      end
      channel_ids.size
    end

    def audit_grant(user_id, kind, name, verb)
      row = Authz::Grant.for_person(user_id).where(kind: kind, name: name).newest_first.first
      return if row.nil?

      audit(row, verb, after: { "user_id" => user_id, kind => name })
    end

    def requested_user_id
      [params[:user_id], params[:user_id_raw]]
        .map { |value| value.to_s.strip.delete_prefix("@").upcase }
        .find(&:present?)
        .to_s
    end

    def redirect_with_alert(message)
      redirect_to admin_people_path, alert: message
    end
  end
end

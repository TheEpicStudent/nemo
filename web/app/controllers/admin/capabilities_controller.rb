module Admin
  class CapabilitiesController < BaseController
    def update
      return redirect_with_alert unless may_grant?

      key = params[:key].to_s
      return redirect_with_alert("#{key} is not a capability") unless Authz.keys.include?(key)
      return redirect_with_alert("#{Authz.label(key)} cannot be delegated") if Authz.locked?(key)

      apply_grant(key, params[:effect].to_s)
      redirect_to admin_person_path(person_user_id), notice: notice_for(key, params[:effect].to_s)
    rescue Authz::Grant::NotAllowedError => e
      redirect_with_alert(e.message)
    end

    def destroy
      return redirect_with_alert unless may_grant?

      key = params[:key].to_s
      return redirect_with_alert("#{key} is not a capability") unless Authz.keys.include?(key)

      Authz::Grant.live.for_person(person_user_id).capabilities.where(name: key)
        .find_each { |grant| revoke(grant, key) }
      Current.forget_roles
      redirect_to admin_person_path(person_user_id), notice: "#{Authz.label(key)} reset to the role default"
    end

    private

    def person_user_id
      params[:person_user_id].to_s.upcase
    end

    def apply_grant(key, effect)
      Authz::Grant.grant!(person_user_id, kind: "capability", name: key, effect: effect,
        by: current_account.user_id, reason: params[:reason].presence)
      audit_change(key, effect)
      Current.forget_roles
    end

    def revoke(grant, key)
      previous_effect = grant.effect
      ActiveRecord::Base.transaction do
        grant.revoke!(by: current_account.user_id)
        Fd::Audit.record(grant, "revoked",
          actor: current_account.user_id, request_id: request.request_id,
          before: { "user_id" => person_user_id, "capability" => key, "effect" => previous_effect },
          after: { "user_id" => person_user_id, "capability" => key, "effect" => "revoked" })
      end
    end

    def audit_change(key, effect)
      row = Authz::Grant.live.for_person(person_user_id).capabilities.find_by(name: key)
      return if row.nil?

      Fd::Audit.record(row, effect == "deny" ? "revoked" : "granted",
        actor: current_account.user_id, request_id: request.request_id,
        after: { "user_id" => person_user_id, "capability" => key, "effect" => effect })
    end

    def notice_for(key, effect)
      effect == "deny" ? "#{Authz.label(key)} taken off them" : "#{Authz.label(key)} given to them"
    end

    def redirect_with_alert(message = nil)
      redirect_to admin_person_path(person_user_id),
        alert: message || Community::Access.why_not(current_account, "analytics.grant")
    end
  end
end

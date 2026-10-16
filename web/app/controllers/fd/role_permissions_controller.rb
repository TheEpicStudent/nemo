module Fd
  class RolePermissionsController < BaseController
    skip_before_action :require_engine
    permit "access.grant"

    def update
      role = params[:role].to_s
      key = params[:key].to_s
      allowed = params[:allowed] == "1"

      writing do
        row = set_override!(role, key, allowed)
        audit(row, allowed ? "granted" : "revoked", entity_id: "#{role}/#{key}",
          after: { "permission" => key, "role" => role, "allowed" => allowed })
      end

      redirect_to admin_roles_path, notice: override_notice(role, key, allowed)
    rescue NotAllowedError => e
      redirect_to admin_roles_path, alert: e.message
    end

    def destroy
      rows = Authz::Override.all.to_a
      return redirect_to(admin_roles_path, alert: "No overrides") if rows.empty?

      writing do
        rows.each do |row|
          audit(row, back_to_default?(row) ? "granted" : "revoked",
            entity_id: "#{row.role}/#{row.capability}", **reset(row))
        end
        Authz::Override.delete_all
        Current.forget_roles
      end

      redirect_to admin_roles_path, notice: "#{rows.size} #{'override'.pluralize(rows.size)} reset"
    end

    private

    class NotAllowedError < StandardError; end

    def set_override!(role, key, allowed)
      check!(role, key, allowed)
      Authz::Override.upsert({ role: role, capability: key, allowed: allowed,
                               changed_by: current_account.user_id, changed_at: Time.current },
        unique_by: %i[role capability])
      Current.forget_roles
      Authz::Override.find_by(role: role, capability: key)
    end

    def check!(role, key, _allowed)
      raise_not_allowed "#{role} is not a role" unless Authz.role_names.include?(role)
      raise_not_allowed "#{role} has every capability" if Authz.superadmin?(role)
      raise_not_allowed "#{key} is not a capability" unless Authz.keys.include?(key)
      raise_not_allowed "#{key} is locked" if Authz.locked?(key)
    end

    def back_to_default?(row)
      Authz.baseline(row.role).include?(row.capability)
    end

    def reset(row)
      {
        before: { "permission" => row.capability, "role" => row.role,
                  "allowed" => row.allowed },
        after: { "permission" => row.capability, "role" => row.role,
                 "allowed" => back_to_default?(row),
                 "why" => "put back to default" }
      }
    end

    def override_notice(role, key, allowed)
      label = "#{Authz.role_label(role)}: #{Authz.label(key)}"
      allowed ? "#{label} allowed" : "#{label} denied"
    end

    def raise_not_allowed(message)
      raise NotAllowedError, message
    end
  end
end

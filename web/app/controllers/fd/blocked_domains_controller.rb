module Fd
  class BlockedDomainsController < BaseController
    permit "app.configure"

    MAX_DOMAIN_LENGTH = 253

    def create
      return deny!("member.deactivate") if effect == BlockedDomain::DEACTIVATE &&
        !current_account&.may?("member.deactivate")

      error = validation_error
      return redirect_with_alert(error) if error

      writing do
        blocked_domain = BlockedDomain.add!(domain: domain_param, by: current_account.user_id,
          match_mode: match_mode, effect: effect, note: params[:note])
        audit(blocked_domain, "added", after: { "domain" => blocked_domain.domain,
          "match_mode" => blocked_domain.match_mode, "effect" => blocked_domain.effect })
      end

      redirect_to return_path, notice: "#{domain_param} added · #{effect}"
    rescue ActiveRecord::RecordNotUnique
      redirect_with_alert("Already on the list")
    end

    def destroy
      blocked_domain = BlockedDomain.active.find_by(id: params[:id])
      return redirect_with_alert("Not on the list") if blocked_domain.nil?

      writing do
        blocked_domain.retire!(by: current_account.user_id)
        audit(blocked_domain, "removed", before: { "active" => true }, after: { "active" => false })
      end

      redirect_to return_path, notice: "#{blocked_domain.domain} removed from the list"
    end

    private

    def return_path(**extra_params) = fd_configuration_path(tab: "domains", **extra_params)

    def domain_param = params[:domain].to_s.strip.downcase.delete_prefix("@")

    def match_mode
      requested = params[:match_mode].to_s
      BlockedDomain::MATCHES.include?(requested) ? requested : BlockedDomain::EXACT
    end

    def effect
      requested = params[:effect].to_s
      BlockedDomain::EFFECTS.include?(requested) ? requested : BlockedDomain::FLAG
    end

    def overridden? = params[:anyway].present?

    def validation_error
      return "Enter a domain" if domain_param.blank?
      return "Keep it under #{MAX_DOMAIN_LENGTH} characters" if domain_param.length > MAX_DOMAIN_LENGTH
      return "#{domain_param} is not a domain" unless BlockedDomain.valid_domain?(domain_param)
      return nil if overridden?

      account_count = BlockedDomain.account_count_on(domain_param, match_mode: match_mode)
      return nil unless BlockedDomain.too_many?(account_count)

      field_error!(:domain, "#{domain_param} is on #{helpers.pluralize(account_count, 'account')} already", domain_param)
    end

    def redirect_with_alert(message)
      redirect_to return_path(do: "domain"), alert: (message unless flash[:field_error])
    end
  end
end

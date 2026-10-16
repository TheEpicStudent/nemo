module Fd
  class SlackAccountsController < BaseController
    skip_before_action :require_engine
    skip_before_action :require_fd
    permit "slack.link"

    STATE = :slack_link_state

    def create
      return redirect_with_alert("Slack linking not configured") unless Slack::Oauth.configured?

      state = SecureRandom.urlsafe_base64(24)
      session[STATE] = state
      redirect_to Slack::Oauth.authorize_url(redirect_uri: back_url, state: state),
        allow_other_host: true
    end

    def callback
      expected_state = session.delete(STATE)
      error = callback_error(expected_state)
      return redirect_with_alert(error) if error

      oauth_response = Slack::Oauth.exchange(code: params[:code], redirect_uri: back_url)
      error = store_token(oauth_response)
      error ? redirect_with_alert(error) : redirect_with_notice("Slack account linked")
    rescue Slack::Oauth::RefusedError, Slack::Oauth::UnavailableError, Slack::Oauth::NotConfiguredError => failure
      redirect_with_alert("Slack did not return a token: #{failure.message}")
    end

    def destroy
      staff_slack = StaffSlack.active_for(current_account.user_id)
      return redirect_with_alert("Slack account not linked") if staff_slack.nil?

      Slack::Oauth.revoke_token(staff_slack.user_token)
      writing do
        staff_slack.revoke_token!(current_account.user_id)
        audit(staff_slack, "unlinked", entity_id: 0, before: { "scopes" => staff_slack.scopes })
      end

      redirect_with_notice("Slack account unlinked")
    end

    private

    def callback_error(expected_state)
      return "Linking cancelled" if params[:error].present?
      return "State mismatch" if
        expected_state.blank? || !ActiveSupport::SecurityUtils.secure_compare(
          params[:state].to_s, expected_state
        )
      return "Slack did not return a code" if params[:code].blank?

      nil
    end

    def store_token(oauth_response)
      authed = oauth_response["authed_user"] || {}
      error = validation_error(authed, oauth_response.dig("team", "id"))
      return error if error

      writing do
        row = StaffSlack.store!(current_account.user_id, token: authed["access_token"],
          team_id: oauth_response.dig("team", "id").to_s, scopes: authed["scope"].to_s)
        audit(row, "linked", entity_id: 0,
          after: { "scopes" => row.scopes, "team_id" => row.team_id })
      end

      nil
    end

    def validation_error(authed, team_id)
      return "Slack returned an app token, not a user token" if authed["access_token"].blank?
      return "Account does not match the signed-in user" if authed["id"] != current_account.user_id
      unless authed["scope"].to_s.split(",").include?(StaffSlack::SCOPE)
        return "Slack granted #{authed["scope"]}, expected #{StaffSlack::SCOPE}"
      end
      if Slack::Oauth.workspace && team_id != Slack::Oauth.workspace
        return "Account belongs to a different workspace"
      end

      nil
    end

    def back_url
      fd_slack_account_callback_url
    end

    def redirect_with_alert(message)
      redirect_to account_path, alert: message
    end

    def redirect_with_notice(message)
      redirect_to account_path, notice: message
    end
  end
end

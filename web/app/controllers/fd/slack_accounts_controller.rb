module Fd
  class SlackAccountsController < BaseController
    skip_before_action :require_engine
    skip_before_action :require_fd
    permit "slack.link"

    STATE = :slack_link_state

    def create
      return redirect_with_alert("linking is not set up on this server") unless Slack::Oauth.configured?

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
      error ? redirect_with_alert(error) : redirect_with_notice("Your Slack account is linked")
    rescue Slack::Oauth::RefusedError, Slack::Oauth::UnavailableError, Slack::Oauth::NotConfiguredError => failure
      redirect_with_alert("slack did not hand over a token: #{failure.message}")
    end

    def destroy
      staff_slack = StaffSlack.active_for(current_account.user_id)
      return redirect_with_alert("your slack account is not linked") if staff_slack.nil?

      Slack::Oauth.revoke_token(staff_slack.user_token)
      writing do
        staff_slack.return_token!(current_account.user_id)
        audit(staff_slack, "unlinked", entity_id: 0, before: { "scopes" => staff_slack.scopes })
      end

      redirect_with_notice("Your Slack account is unlinked; messages now send through nemo")
    end

    private

    def callback_error(expected_state)
      return "linking was cancelled" if params[:error].present?
      return "that link attempt did not match this browser, try again" if
        expected_state.blank? || !ActiveSupport::SecurityUtils.secure_compare(
          params[:state].to_s, expected_state
        )
      return "slack did not send a code back" if params[:code].blank?

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
      return "slack granted an app token, not a token for you" if authed["access_token"].blank?
      return "that is not the account you are signed in as" if authed["id"] != current_account.user_id
      unless authed["scope"].to_s.split(",").include?(StaffSlack::SCOPE)
        return "slack granted #{authed["scope"]}, which is not #{StaffSlack::SCOPE}"
      end
      if Slack::Oauth.workspace && team_id != Slack::Oauth.workspace
        return "that account is in a different workspace"
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

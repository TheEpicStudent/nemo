class SessionsController < ApplicationController
  layout "landing"
  skip_before_action :require_account

  RETURN_PATH = %r{\A/(?![/\\])}

  def new
    redirect_to root_path
  end

  def create
    auth = request.env["omniauth.auth"]
    slack_id = auth&.extra&.raw_info&.[]("slack_id")

    if slack_id.blank?
      reset_session
      return redirect_to auth_failure_path(message: "no_slack_id")
    end

    staff = Account.find_or_create_by!(user_id: slack_id)
    Prometheus::Mirror.refresh(staff.user_id)
    return_to = safe_return_to(session[:return_to])
    reset_session
    session[:user_id] = staff.user_id
    redirect_to return_to || root_path, notice: sign_in_notice(staff)
  end

  def failure
    @message = params[:message]
    flash.clear
  end

  def destroy
    reset_session
    redirect_to root_path
  end

  private

  def safe_return_to(path)
    path if path.is_a?(String) && path.match?(RETURN_PATH)
  end

  def sign_in_notice(staff)
    roles = Authz.effective_roles(staff.user_id).map { |role| Authz.role_label(role) }
    extras = Authz::Grant.live.for_person(staff.user_id).capabilities
      .where(effect: "allow").count
    return "Signed in" if roles.empty? && extras.zero?
    return "Signed in as #{roles.to_sentence}" if extras.zero?

    "Signed in as #{roles.presence&.to_sentence || 'a member'}, " \
      "#{extras} #{'extra scope'.pluralize(extras)}"
  end
end

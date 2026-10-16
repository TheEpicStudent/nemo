module Settings
  class RequestsController < BaseController
    before_action :require_reviewer, only: [:index, :decide]

    DECIDED_LIMIT = 50

    RANK = { Api::AccessRequest::PENDING => 0, Api::AccessRequest::APPROVED => 1,
             Api::AccessRequest::DECLINED => 2, Api::AccessRequest::WITHDRAWN => 3 }.freeze

    def index
      pending = Api::AccessRequest.queue.includes(:app).to_a
      decided = Api::AccessRequest.decided.includes(:app)
        .order(decided_at: :desc).limit(DECIDED_LIMIT).to_a

      @rows = pending + decided.sort_by { |row| [RANK.fetch(row.state, 9), -row.decided_at.to_i] }
      @pending_count = pending.size
      @names = Fd::Names.for(named_in(@rows))
    end

    def create
      app = Api::App.live.find_by(id: params[:app_id], owner_user_id: member_id)
      return redirect_with_alert("Not your app") if app.nil?

      Api::AccessRequest.submit!(app, reason: params[:reason])
      redirect_to settings_keys_path, notice: "Access requested for #{app.name}"
    rescue Api::AccessRequest::ReasonTooShortError
      redirect_with_alert "Enter a reason"
    rescue Api::AccessRequest::StateConflictError
      redirect_with_alert "Access already requested"
    end

    def withdraw
      access_request = Api::AccessRequest.pending.includes(:app).find_by(id: params[:id])
      return redirect_with_alert("Not your request") if access_request&.app&.owner_user_id != member_id

      access_request.withdraw!
      redirect_to settings_keys_path, notice: "Withdrawn"
    end

    def decide
      access_request = Api::AccessRequest.pending.includes(:app).find_by(id: params[:id])
      return redirect_to(settings_requests_path, alert: "Already settled") if access_request.nil?

      approved = params[:verdict].to_s.casecmp?("approve")
      access_request.public_send(approved ? :approve! : :decline!, by: member_id, note: params[:note])
      verdict_label = approved ? "Approved" : "Declined"
      redirect_to settings_requests_path, notice: "#{verdict_label} #{access_request.app.name}"
    end

    private

    def named_in(rows)
      rows.flat_map { |row| [row.app.owner_user_id, row.decided_by] }.compact.uniq
    end

    def redirect_with_alert(message)
      redirect_to settings_keys_path, alert: message
    end

    def require_reviewer
      return if Authz.holds?(current_account, "api.review")

      redirect_to settings_keys_path, alert: "API review access required"
    end
  end
end

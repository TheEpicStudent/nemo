module Settings
  class ConsentsController < BaseController
    def update
      return redirect_with_alert(turned_off) if api_off?

      key = params[:scope].to_s
      Api::Scope.fetch(key)
      app = requested_app
      return redirect_with_alert("No such app") if params[:app_id].present? && app.nil?

      granted = params[:on] == "1"
      Api::Consent.set!(member_id, app&.id, key, granted, via: "dashboard")

      redirect_to settings_permissions_path, notice: notice_for(app, key, granted)
    rescue Api::Scope::UnknownError => e
      redirect_with_alert(e.message)
    end

    private

    def requested_app
      return nil if params[:app_id].blank?

      app = Api::App.live.find_by(id: params[:app_id])
      app&.approved? ? app : nil
    end

    def notice_for(app, key, granted)
      scope_label = Api::Scope.label(key).downcase
      app_label = app ? app.name : "Every app"
      granted ? "#{app_label} may ask about #{scope_label}" : "#{app_label} may no longer ask"
    end

    def redirect_with_alert(message)
      redirect_to settings_permissions_path, alert: message
    end
  end
end

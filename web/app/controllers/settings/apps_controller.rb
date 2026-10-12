module Settings
  class AppsController < BaseController
    def create
      return redirect_with_alert(turned_off) if api_off?

      app = nil
      ActiveRecord::Base.transaction do
        app = Api::App.register!(member_id, name: params[:name], blurb: params[:blurb])
        Api::AccessRequest.ask!(app, reason: params[:reason])
      end

      redirect_to settings_keys_path, notice: "Asked for access for #{app.name}"
    rescue Api::App::UnnamedError
      redirect_with_alert("Name the app")
    rescue Api::App::TooThinError
      redirect_with_alert("Describe what the app does, in a sentence")
    rescue Api::AccessRequest::TooThinError
      redirect_with_alert("Describe what the app needs access for")
    end

    def destroy
      app = Api::App.live.find_by(id: params[:id], owner_user_id: member_id)
      return redirect_with_alert("That app is not yours") if app.nil?

      app.retire!(by: member_id)
      Api::Event.record!("app_retired", actor: member_id, subject: app.name)

      redirect_to settings_keys_path, notice: "Deleted #{app.name}"
    end

    private

    def redirect_with_alert(message)
      redirect_to settings_keys_path, alert: message
    end
  end
end

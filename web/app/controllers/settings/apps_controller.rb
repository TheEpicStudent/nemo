module Settings
  class AppsController < BaseController
    def create
      return redirect_with_alert(turned_off) if api_off?

      app = nil
      ActiveRecord::Base.transaction do
        app = Api::App.register!(member_id, name: params[:name], blurb: params[:blurb])
        Api::AccessRequest.submit!(app, reason: params[:reason])
      end

      redirect_to settings_keys_path, notice: "Access requested for #{app.name}"
    rescue Api::App::NameBlankError
      redirect_with_alert("Enter a name")
    rescue Api::App::BlurbTooShortError
      redirect_with_alert("Enter a description")
    rescue Api::AccessRequest::ReasonTooShortError
      redirect_with_alert("Enter a reason")
    end

    def destroy
      app = Api::App.live.find_by(id: params[:id], owner_user_id: member_id)
      return redirect_with_alert("Not your app") if app.nil?

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

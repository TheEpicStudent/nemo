module Fd
  class PublicLogController < BaseController
    permit "app.configure"

    before_action :require_event, only: [:event, :reset]

    def channel
      channel_id = params[:channel_id].to_s.strip
      return redirect_with_alert("Select a channel") if channel_id.blank?
      return redirect_with_alert("#{channel_id} is not a channel") unless channel_exists?(channel_id)

      writing { audit_setting(AppSetting.write(PublicLog::CHANNEL_KEY, channel_id, by: current_account.user_id)) }
      redirect_to return_path, notice: "Public log channel saved"
    end

    def event
      template = params[:template].to_s.gsub("\r\n", "\n").strip
      error = template_error(template)
      return redirect_with_alert(error) if error

      writing do
        audit_setting(AppSetting.set_enabled(PublicLog.enabled_key(@event), params[:on].present?,
          by: current_account.user_id))
        write_template(template)
      end
      redirect_to return_path, notice: "#{PublicLog.label(@event)} saved"
    end

    def reset
      writing do
        setting = AppSetting.find_by(key: PublicLog.template_key(@event))
        if setting
          setting.destroy!
          audit(setting, "reset")
        end
      end
      redirect_to return_path, notice: "#{PublicLog.label(@event)} template reset"
    end

    private

    def require_event
      @event = params[:event].to_s
      head :not_found unless PublicLog.event?(@event)
    end

    def return_path
      fd_configuration_path(tab: "public_log")
    end

    def template_error(template)
      return "Enter a template" if template.blank?
      return "Keep it under #{PublicLog::MAX_TEMPLATE_LENGTH} characters" if template.length > PublicLog::MAX_TEMPLATE_LENGTH

      unknown = PublicLog.unknown_variables(@event, template)
      return "Unknown variable #{unknown.map { |name| "{#{name}}" }.join(", ")}" if unknown.any?

      nil
    end

    def write_template(template)
      return nil if template == PublicLog.template(@event) && !PublicLog.customised?(@event)

      audit_setting(AppSetting.write(PublicLog.template_key(@event), template, by: current_account.user_id))
    end

    def channel_exists?(channel_id)
      Analytics::DimChannel.where(channel_id: channel_id).exists?
    end

    def audit_setting(setting)
      audit(setting, "tuned") if setting
      setting
    end

    def redirect_with_alert(message)
      redirect_to return_path, alert: message
    end
  end
end

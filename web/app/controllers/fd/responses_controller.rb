module Fd
  class ResponsesController < BaseController
    permit "app.configure"

    MAX_BODY_LENGTH = 4000
    MAX_COOLDOWN_DAYS = 365

    def autoresponse
      error = autoresponse_error
      return redirect_with_alert(error) if error

      writing do
        audit_setting(AppSetting.flip(AppSetting::AUTORESPONSE_ON, params[:on].present?,
          by: current_account.user_id))
        audit_setting(AppSetting.set_words(AppSetting::AUTORESPONSE_EMOJI, params[:emoji],
          by: current_account.user_id))
        write_if_present(AppSetting::AUTORESPONSE_CHANNEL, channel_id)
        write_if_present(AppSetting::AUTORESPONSE_BODY, body)
        write_if_present(AppSetting::AUTORESPONSE_COOLDOWN, cooldown.positive? ? cooldown.to_s : "")
      end

      redirect_to return_path, notice: "Autoresponse saved"
    end

    def unsub_shield
      link = params[:link].to_s.strip
      return redirect_with_alert("That is not a valid link") if link.present? && !link.match?(%r{\Ahttps?://})

      writing do
        audit_setting(AppSetting.flip(AppSetting::UNSUB_SHIELD_ON, params[:on].present?,
          by: current_account.user_id))
        write_if_present(AppSetting::UNSUB_SHIELD_LINK, link)
      end

      redirect_to return_path, notice: "Unsubscribe shield saved"
    end

    private

    def return_path
      fd_configuration_path(tab: "responses")
    end

    def channel_id
      @channel_id ||= params[:channel_id].to_s.strip
    end

    def body
      params[:body].to_s.strip
    end

    def cooldown
      params[:cooldown_days].to_s.strip.to_i
    end

    def autoresponse_error
      return nil if params[:on].blank?

      return "say what to answer with" if body.blank?
      return "keep it under #{MAX_BODY_LENGTH} characters" if body.length > MAX_BODY_LENGTH
      return "pick which channel to watch" if channel_id.blank?
      return "#{channel_id} is not a channel" unless channel_exists?(channel_id)
      return "pick at least one emoji" if requested_emoji.empty?
      return "say how many days, from 1 to #{MAX_COOLDOWN_DAYS}" unless cooldown.between?(1, MAX_COOLDOWN_DAYS)

      nil
    end

    def requested_emoji
      Array(params[:emoji]).flat_map { |value| value.to_s.split(",") }
        .map { |name| name.strip.delete_prefix(":").delete_suffix(":") }.reject(&:blank?)
    end

    def channel_exists?(channel_id)
      Analytics::DimChannel.where(channel_id: channel_id).exists?
    end

    def write_if_present(key, value)
      return nil if value.blank?

      audit_setting(AppSetting.write(key, value, by: current_account.user_id))
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

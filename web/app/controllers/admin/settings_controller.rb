module Admin
  class SettingsController < BaseController
    SOONEST = Fd::AppSetting::SOONEST

    JOIN_MODE_NOTICES = {
      Fd::AppSetting::ON => "nemo joins every public channel",
      Fd::AppSetting::GUARDED => "nemo joins guarded and configured channels",
      Fd::AppSetting::OFF => "nemo joins configured channels only"
    }.freeze

    def show
      @join_mode = Fd::AppSetting.join_mode
      @soon_hours = Fd::AppSetting.sweep_soon_hours
      @tells_member = Fd::AppSetting.sweep_tells_member?
      @firehouse = Fd::AppSetting.firehouse_channel
      @reports_channel = Fd::AppSetting.reports_channel
      @log_channel = Fd::AppSetting.log_channel
      @react_channels = Fd::AppSetting.case_react_channels
      configured_ids = ([@firehouse, @reports_channel, @log_channel] + @react_channels).compact.uniq
      @channels_by_id = Analytics::DimChannel.where(channel_id: configured_ids).index_by(&:channel_id)
      @seats = configured_ids.index_with { |channel_id| Fd::ChannelMembership.seat(channel_id) }
    end

    def join_mode
      mode = params[:mode].to_s.strip.downcase
      return redirect_with_alert("That is not a valid join mode") unless Fd::AppSetting::MODES.include?(mode)
      return redirect_to admin_settings_path if mode == Fd::AppSetting.join_mode

      audit_setting(Fd::AppSetting.set_join_mode(mode, by: current_account.user_id))
      redirect_to admin_settings_path, notice: JOIN_MODE_NOTICES.fetch(mode)
    end

    def sweep
      hours = params[:soon_hours].to_s.strip.to_i
      return redirect_with_alert("Enter a number of hours, from 1 to #{SOONEST}") unless hours.between?(1, SOONEST)

      audit_setting(Fd::AppSetting.write(Fd::AppSetting::SWEEP_SOON_HOURS, hours.to_s,
        by: current_account.user_id))
      audit_setting(Fd::AppSetting.flip(Fd::AppSetting::SWEEP_TELLS_MEMBER, params[:tells].present?,
        by: current_account.user_id))
      redirect_to admin_settings_path, notice: "Sweep settings saved"
    end

    def firehouse
      save_channel(Fd::AppSetting::FIREHOUSE, "The firehouse is now")
    end

    def reports_channel
      save_channel(Fd::AppSetting::REPORTS, "Shroud reports now post to")
    end

    def log_channel
      save_channel(Fd::AppSetting::LOGS, "Nemo logs now post to")
    end

    def add_react
      channel_id = params[:channel_id].to_s.strip
      return redirect_with_alert("Select a channel") if channel_id.blank?
      return redirect_with_alert("#{channel_id} is not a channel") unless channel_exists?(channel_id)

      channel_ids = Fd::AppSetting.case_react_channels
      return redirect_to admin_settings_path if channel_ids.include?(channel_id)

      audit_setting(Fd::AppSetting.set_case_react_channels(channel_ids + [channel_id],
        by: current_account.user_id))
      redirect_to admin_settings_path,
        notice: "An hourglass in ##{name_of(channel_id)} now opens a case"
    end

    def drop_react
      channel_id = params[:channel_id].to_s.strip
      channel_ids = Fd::AppSetting.case_react_channels - [channel_id]
      audit_setting(Fd::AppSetting.set_case_react_channels(channel_ids, by: current_account.user_id))
      redirect_to admin_settings_path, notice: "##{name_of(channel_id)} no longer opens cases"
    end

    private

    def save_channel(key, notice)
      channel_id = params[:channel_id].to_s.strip
      return redirect_with_alert("Select a channel") if channel_id.blank?
      return redirect_with_alert("#{channel_id} is not a channel") unless channel_exists?(channel_id)

      audit_setting(Fd::AppSetting.write(key, channel_id, by: current_account.user_id))
      redirect_to admin_settings_path, notice: "#{notice} ##{name_of(channel_id)}"
    end

    def audit_setting(setting)
      audit(setting, "tuned") if setting
      setting
    end

    def channel_exists?(channel_id)
      Analytics::DimChannel.where(channel_id: channel_id).exists?
    end

    def name_of(channel_id)
      Analytics::DimChannel.find_by(channel_id: channel_id)&.name.presence || channel_id
    end

    def redirect_with_alert(message = "that is not allowed")
      redirect_to admin_settings_path, alert: message
    end
  end
end

module Admin
  class SettingsController < BaseController
    MEMBER_ID = /\A[UW][A-Z0-9]{2,}\z/

    def show
      @join_mode = Fd::AppSetting.join_mode
      @soon_hours = Fd::AppSetting.sweep_soon_hours
      @tells_member = Fd::AppSetting.sweep_tells_member?
      @deactivate_mode = Fd::AppSetting.deactivate_mode
      @session_reset_mode = Fd::AppSetting.session_reset_mode
      @reset_strikes = Fd::AppSetting.session_reset_strikes
      @reset_max = Fd::AppSetting.session_reset_max
      @firehouse = Fd::AppSetting.firehouse_channel
      @reports_channel = Fd::AppSetting.reports_channel
      @log_channel = Fd::AppSetting.log_channel
      @react_channels = Fd::AppSetting.case_react_channels
      @trusted_senders = Fd::AppSetting.trusted_senders
      configured_ids = ([@firehouse, @reports_channel, @log_channel] + @react_channels).compact.uniq
      @channels_by_id = Analytics::DimChannel.where(channel_id: configured_ids).index_by(&:channel_id)
      @memberships = configured_ids.index_with { |channel_id| Fd::ChannelMembership.membership_for(channel_id) }
    end

    def join_mode
      mode = params[:mode].to_s.strip.downcase
      return redirect_with_alert("That is not a valid join mode") unless Fd::AppSetting::MODES.include?(mode)
      return redirect_to admin_settings_path if mode == Fd::AppSetting.join_mode

      audit_setting(Fd::AppSetting.set_join_mode(mode, by: current_account.user_id))
      redirect_to admin_settings_path, notice: "Join mode set to #{AdminHelper::JOIN_MODES.fetch(mode)}"
    end

    def sweep
      hours = params[:soon_hours].to_s.strip.to_i
      return redirect_with_alert("Enter a number of hours, from 1 to #{Fd::AppSetting::MAX_SOON_HOURS}") unless hours.between?(1, Fd::AppSetting::MAX_SOON_HOURS)

      audit_setting(Fd::AppSetting.write(Fd::AppSetting::SWEEP_SOON_HOURS, hours.to_s,
        by: current_account.user_id))
      audit_setting(Fd::AppSetting.set_enabled(Fd::AppSetting::SWEEP_TELLS_MEMBER, params[:tells].present?,
        by: current_account.user_id))
      redirect_to admin_settings_path, notice: "Guard expiry settings saved"
    end

    def accounts
      modes = { Fd::AppSetting::DEACTIVATE => params[:deactivate].to_s.strip.downcase,
                Fd::AppSetting::SESSION_RESET => params[:session_reset].to_s.strip.downcase }
      return redirect_with_alert("That is not a valid mode") unless modes.values.all? { |mode|
        Fd::AppSetting::ACCOUNT_MODES.include?(mode)
      }

      strikes = Integer(params[:strikes].to_s.strip, 10, exception: false)
      unless strikes&.between?(1, Fd::AppSetting::MAX_STRIKES)
        return redirect_with_alert("Enter a number of replies, from 1 to #{Fd::AppSetting::MAX_STRIKES}")
      end

      resets = Integer(params[:resets].to_s.strip, 10, exception: false)
      unless resets&.between?(0, Fd::AppSetting::MAX_RESETS)
        return redirect_with_alert("Enter a number of sign-outs, from 0 to #{Fd::AppSetting::MAX_RESETS}")
      end

      modes.merge(Fd::AppSetting::SESSION_RESET_STRIKES => strikes.to_s,
                  Fd::AppSetting::SESSION_RESET_MAX => resets.to_s).each do |key, value|
        next if Fd::AppSetting.value(key) == value

        audit_setting(Fd::AppSetting.write(key, value, by: current_account.user_id))
      end
      redirect_to admin_settings_path, notice: "Account action settings saved"
    end

    def firehouse
      save_channel(Fd::AppSetting::FIREHOUSE, "Firehouse channel")
    end

    def reports_channel
      save_channel(Fd::AppSetting::REPORTS, "Shroud reports channel")
    end

    def log_channel
      save_channel(Fd::AppSetting::LOGS, "Internal logs channel")
    end

    def add_react
      channel_id = params[:channel_id].to_s.strip
      return redirect_with_alert("Select a channel") if channel_id.blank?
      return redirect_with_alert("#{channel_id} is not a known channel") unless channel_exists?(channel_id)

      channel_ids = Fd::AppSetting.case_react_channels
      return redirect_to admin_settings_path if channel_ids.include?(channel_id)

      audit_setting(Fd::AppSetting.set_case_react_channels(channel_ids + [channel_id],
        by: current_account.user_id))
      redirect_to admin_settings_path,
        notice: "##{name_of(channel_id)} added to case reaction channels"
    end

    def remove_react
      channel_id = params[:channel_id].to_s.strip
      channel_ids = Fd::AppSetting.case_react_channels - [channel_id]
      audit_setting(Fd::AppSetting.set_case_react_channels(channel_ids, by: current_account.user_id))
      redirect_to admin_settings_path, notice: "##{name_of(channel_id)} removed from case reaction channels"
    end

    def add_trusted_sender
      user_id = params[:user_id].to_s.strip.upcase
      return redirect_with_alert("Select a member") if user_id.blank?
      return redirect_with_alert("#{user_id} is not a member id") unless user_id.match?(MEMBER_ID)

      user_ids = Fd::AppSetting.trusted_senders
      return redirect_to admin_settings_path if user_ids.include?(user_id)

      audit_setting(Fd::AppSetting.set_trusted_senders(user_ids + [user_id], by: current_account.user_id))
      redirect_to admin_settings_path, notice: "@#{user_id} added to trusted senders"
    end

    def remove_trusted_sender
      user_id = params[:user_id].to_s.strip
      user_ids = Fd::AppSetting.trusted_senders - [user_id]
      audit_setting(Fd::AppSetting.set_trusted_senders(user_ids, by: current_account.user_id))
      redirect_to admin_settings_path, notice: "@#{user_id} removed from trusted senders"
    end

    private

    def save_channel(key, label)
      channel_id = params[:channel_id].to_s.strip
      return redirect_with_alert("Select a channel") if channel_id.blank?
      return redirect_with_alert("#{channel_id} is not a known channel") unless channel_exists?(channel_id)

      audit_setting(Fd::AppSetting.write(key, channel_id, by: current_account.user_id))
      redirect_to admin_settings_path, notice: "#{label} set to ##{name_of(channel_id)}"
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

    def redirect_with_alert(message = "Not allowed")
      redirect_to admin_settings_path, alert: message
    end
  end
end

module Fd
  class AppSetting < ApplicationRecord
    self.table_name = "fd.app_settings"
    self.primary_key = "key"

    JOIN_MODE = "nemo.join_mode".freeze
    FIREHOUSE = "nemo.firehouse_channel".freeze
    REPORTS = "nemo.reports_channel".freeze
    LOGS = "nemo.log_channel".freeze
    REACT_CHANNELS = "nemo.case_react_channels".freeze

    AUTORESPONSE_ON = "nemo.autoresponse_on".freeze
    AUTORESPONSE_EMOJI = "nemo.autoresponse_emoji".freeze
    AUTORESPONSE_CHANNEL = "nemo.autoresponse_channel".freeze
    AUTORESPONSE_BODY = "nemo.autoresponse_body".freeze
    AUTORESPONSE_COOLDOWN = "nemo.autoresponse_cooldown_days".freeze
    UNSUB_SHIELD_ON = "nemo.unsub_shield_on".freeze
    UNSUB_SHIELD_LINK = "nemo.unsub_shield_link".freeze

    SWEEP_SOON_HOURS = "nemo.sweep_soon_hours".freeze
    SWEEP_TELLS_MEMBER = "nemo.sweep_tells_member".freeze

    SOON_FALL_BACK = 36
    SOONEST = 720

    COOLDOWN_FALL_BACK = 7

    ON = "on".freeze
    GUARDED = "guarded".freeze
    OFF = "off".freeze
    MODES = [ON, GUARDED, OFF].freeze
    FALL_BACK = GUARDED

    def self.join_mode
      mode = find_by(key: JOIN_MODE)&.value.to_s.strip.downcase
      MODES.include?(mode) ? mode : FALL_BACK
    end

    def self.value(key)
      find_by(key: key)&.value.to_s.strip
    end

    def self.write(key, value, by:)
      setting = find_or_initialize_by(key: key)
      setting.update!(value: value, changed_by: by, changed_at: Time.current)
      setting
    end

    def self.firehouse_channel
      value(FIREHOUSE).presence
    end

    def self.set_firehouse_channel(channel_id, by:)
      write(FIREHOUSE, channel_id, by: by)
    end

    def self.reports_channel
      value(REPORTS).presence
    end

    def self.log_channel
      value(LOGS).presence
    end

    def self.case_react_channels
      value(REACT_CHANNELS).split(",").map(&:strip).reject(&:blank?)
    end

    def self.set_case_react_channels(ids, by:)
      channel_csv = Array(ids).map(&:to_s).map(&:strip).reject(&:blank?).uniq.join(",")
      return where(key: REACT_CHANNELS).destroy_all && nil if channel_csv.blank?

      write(REACT_CHANNELS, channel_csv, by: by)
    end

    def self.on?(key)
      value(key) == ON
    end

    def self.flip(key, on, by:)
      write(key, on ? ON : OFF, by: by)
    end

    def self.words(key)
      value(key).split(",").map(&:strip).reject(&:blank?).uniq
    end

    def self.set_words(key, values, by:)
      normalized = Array(values).flat_map { |word| word.to_s.split(",") }
        .map { |word| word.strip.delete_prefix(":").delete_suffix(":") }
        .reject(&:blank?).uniq
      return where(key: key).destroy_all && nil if normalized.empty?

      write(key, normalized.join(","), by: by)
    end

    def self.autoresponse_emoji = words(AUTORESPONSE_EMOJI)

    def self.sweep_soon_hours
      hours = value(SWEEP_SOON_HOURS).to_i
      hours.positive? ? hours : SOON_FALL_BACK
    end

    def self.sweep_tells_member?
      value(SWEEP_TELLS_MEMBER) != OFF
    end

    def self.autoresponse_cooldown_days
      days = value(AUTORESPONSE_COOLDOWN).to_i
      days.positive? ? days : COOLDOWN_FALL_BACK
    end

    def self.set_join_mode(mode, by:)
      raise ArgumentError, "#{mode} is not a join mode" unless MODES.include?(mode)

      setting = find_or_initialize_by(key: JOIN_MODE)
      setting.update!(value: mode, changed_by: by, changed_at: Time.current)
      setting
    end
  end
end

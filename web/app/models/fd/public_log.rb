module Fd
  class PublicLog
    EVENTS = YAML.load_file(Rails.root.join("../db/public_log_events.yml")).fetch("events").freeze
    CHANNEL_KEY = "nemo.public_log_channel".freeze
    MAX_TEMPLATE_LENGTH = 1000
    VARIABLE = /\{(\w+)\}/

    def self.events = EVENTS.keys

    def self.event?(event) = EVENTS.key?(event.to_s)

    def self.label(event) = EVENTS.fetch(event).fetch("label")

    def self.variables(event) = EVENTS.fetch(event).fetch("variables")

    def self.default_template(event) = EVENTS.fetch(event).fetch("template")

    def self.enabled_key(event) = "nemo.public_log.#{event}.on"

    def self.template_key(event) = "nemo.public_log.#{event}.template"

    def self.channel = AppSetting.value(CHANNEL_KEY).presence

    def self.enabled?(event)
      case AppSetting.value(enabled_key(event)).downcase
      when AppSetting::ON then true
      when AppSetting::OFF then false
      else EVENTS.fetch(event).fetch("enabled")
      end
    end

    def self.template(event)
      AppSetting.value(template_key(event)).presence || default_template(event)
    end

    def self.customised?(event) = AppSetting.value(template_key(event)).present?

    def self.unknown_variables(event, template)
      template.scan(VARIABLE).flatten.uniq - variables(event)
    end
  end
end

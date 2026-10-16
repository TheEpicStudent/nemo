module Engine
  class Setting < ApplicationRecord
    self.table_name = "engine_setting"

    class RefusedError < ArgumentError; end

    ENGINE = "engine".freeze
    CADENCE = "cadence".freeze
    ENABLED = "enabled".freeze
    RETENTION = "retention_days".freeze
    RETAIN_ALL = "keep".freeze
    MAX_RETENTION_DAYS = 3650

    ENGINE_SETTINGS = {
      "run_at" => { label: "Nightly run time", default: "03:00", kind: :time },
      "budget_minutes" => { label: "Nightly budget (minutes)", default: "480", kind: :number,
                            min: 5, max: 720 },
      "breaker_mode" => { label: "Breaker mode", default: "observe", kind: :choice,
                          choices: %w[observe on off] },
      "backfill_ceiling" => { label: "Backfill ceiling (requests)", default: "1000",
                              kind: :number, min: 0, max: 100_000 },
      "reclaim_seconds" => { label: "Dead run reclaim (seconds)", default: "900",
                             kind: :number, min: 300, max: 21_600 }
    }.freeze

    def self.choices(name)
      ENGINE_SETTINGS.dig(name.to_s, :choices)
    end

    def self.backfill_ceiling
      value(ENGINE, "backfill_ceiling").to_i
    end

    def self.overrides
      Current.engine_settings ||= pluck(:source, :name, :value)
        .to_h { |source, name, value| [[source, name], value] }
    end

    def self.raw(source, name)
      overrides[[source.to_s, name.to_s]]
    end

    def self.value(source, name)
      raw(source, name) || default(source, name)
    end

    def self.default(source, name)
      return ENGINE_SETTINGS.fetch(name.to_s).fetch(:default) if source.to_s == ENGINE
      return Source[source].cadence if name.to_s == CADENCE
      return "true" if name.to_s == ENABLED
      return RETAIN_ALL if name.to_s == RETENTION

      Source[source].limit(name).fetch("default").to_s
    end

    def self.changed?(source, name)
      raw(source, name).present?
    end

    def self.on?(source)
      value(source, ENABLED).to_s != "false"
    end

    def self.cadence(source)
      value(source, CADENCE)
    end

    def self.number(source, name)
      value(source, name).to_i
    end

    def self.set!(source, name, value, by:)
      value = checked(source.to_s, name.to_s, value.to_s.strip)
      row = find_or_initialize_by(source: source.to_s, name: name.to_s)
      row.update!(value: value, changed_by: by, changed_at: Time.current)
      Current.forget_engine_settings
      row
    end

    def self.reset!(source, name, by:)
      row = find_by(source: source.to_s, name: name.to_s)
      return nil if row.nil?

      row.destroy!
      Current.forget_engine_settings
      row
    end

    def self.checked(source, name, value)
      raise RefusedError, "#{name} cannot be blank" if value.blank?

      if source == ENGINE
        return checked_engine(name, value)
      end

      case name
      when CADENCE
        return value if Source::CADENCES.include?(value)

        raise RefusedError, "#{value} is not a cadence"
      when ENABLED
        return value if %w[true false].include?(value)

        raise RefusedError, "#{value} is not true or false"
      when RETENTION
        checked_retention(source, value)
      else
        in_bounds(Source[source].limit(name), name, value)
      end
    end

    def self.checked_retention(source, value)
      return RETAIN_ALL if value.casecmp(RETAIN_ALL).zero?

      floor = Source[source].prune_floor_days
      raise RefusedError, "#{source} has no retention setting" if floor.nil?

      in_bounds({ "min" => floor, "max" => MAX_RETENTION_DAYS }, RETENTION, value)
    end

    def self.checked_engine(name, value)
      definition = ENGINE_SETTINGS.fetch(name) { raise RefusedError, "#{name} is not an engine setting" }
      if definition[:kind] == :switch
        return value if %w[true false].include?(value)

        raise RefusedError, "#{value} is not true or false"
      end
      if definition[:kind] == :choice
        return value if definition[:choices].include?(value)

        raise RefusedError, "#{value} is not one of #{definition[:choices].join(', ')}"
      end
      return value if definition[:kind] == :time && value.match?(/\A([01]\d|2[0-3]):[0-5]\d\z/)
      raise RefusedError, "#{value} is not a time of day" if definition[:kind] == :time

      in_bounds(definition.transform_keys(&:to_s), name, value)
    end

    def self.in_bounds(bounds, name, value)
      raise RefusedError, "#{name} must be a number" unless value.match?(/\A\d+\z/)

      number = value.to_i
      low = bounds.fetch("min")
      high = bounds.fetch("max")
      return value if number.between?(low, high)

      raise RefusedError, "#{name} must be between #{low} and #{high}"
    end
  end
end

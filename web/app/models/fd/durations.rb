module Fd
  module Durations
    CUSTOM = "custom".freeze
    LENGTHS = {
      "15m" => 15.minutes, "30m" => 30.minutes, "1h" => 1.hour, "2h" => 2.hours,
      "6h" => 6.hours, "12h" => 12.hours, "24h" => 24.hours
    }.freeze
    LABELS = {
      "15m" => "15 minutes", "30m" => "30 minutes", "1h" => "1 hour", "2h" => "2 hours",
      "6h" => "6 hours", "12h" => "12 hours", "24h" => "24 hours"
    }.freeze

    def self.options(prefix = "")
      LABELS.map { |key, label| ["#{prefix}#{label}", key] } + [["Custom end", CUSTOM]]
    end

    def self.read(key, date_text, time_text, from: nil, now: Time.current)
      key = key.to_s
      return [[from, now].compact.max + LENGTHS.fetch(key), nil] if LENGTHS.key?(key)
      return [nil, nil] unless key == CUSTOM

      ends, error = EndTime.read(date_text, time_text)
      return [nil, error] if error
      return [nil, "Enter the end date"] if ends.nil?
      return [nil, "End must be in the future"] if ends <= now

      [ends, nil]
    end
  end
end

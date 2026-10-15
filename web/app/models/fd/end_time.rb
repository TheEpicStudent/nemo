module Fd
  module EndTime
    TIME = /\A([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\z/

    def self.read(date_text, time_text)
      date_text = date_text.to_s.strip
      time_text = time_text.to_s.strip
      return [nil, time_text.present? ? "Enter a date for the end time" : nil] if date_text.blank?

      on = Date.strptime(date_text, "%Y-%m-%d")
      return [on.end_of_day, nil] if time_text.blank?

      match = TIME.match(time_text)
      return [nil, "#{time_text} is not a time"] if match.nil?

      [Time.utc(on.year, on.month, on.day, match[1].to_i, match[2].to_i), nil]
    rescue Date::Error
      [nil, "#{date_text} is not a date"]
    end
  end
end

module Fd
  module ShortDate
    def self.for(time, today: Date.current)
      time.strftime(time.year == today.year ? "%-d %b" : "%-d %b %Y")
    end

    def self.ending(time, today: Date.current)
      utc = time.utc
      return self.for(utc, today: today) if utc.hour == 23 && utc.min == 59

      "#{self.for(utc, today: today)}, #{utc.strftime('%H:%M')} UTC"
    end
  end
end

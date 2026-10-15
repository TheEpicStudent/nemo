module Fd
  module ShortDate
    def self.for(time, today: Date.current)
      time.strftime(time.year == today.year ? "%-d %b" : "%-d %b %Y")
    end
  end
end

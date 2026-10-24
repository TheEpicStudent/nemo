module Slack
  module UnicodeEmoji
    PATH = Rails.root.join("config/slack_emoji.json")
    SKIN_TONE = /\Askin-tone-([2-6])\z/
    SKIN_TONE_BASE = 0x1F3FB
    VARIATION_SELECTOR = "️".freeze

    def self.for(name, unicode: nil, skin_tone: nil)
      from_codepoints(unicode) || with_skin_tone(table[name.to_s], skin_tone)
    end

    def self.skin_tone(name)
      name.to_s[SKIN_TONE, 1]&.to_i
    end

    def self.from_codepoints(unicode)
      return nil if unicode.blank?

      unicode.to_s.split("-").map { |part| Integer(part, 16) }.pack("U*")
    rescue ArgumentError, RangeError
      nil
    end

    def self.with_skin_tone(text, skin_tone)
      return text if text.nil? || !skin_tone.to_i.between?(2, 6)

      text.delete(VARIATION_SELECTOR) + [SKIN_TONE_BASE + skin_tone.to_i - 2].pack("U")
    end

    def self.table
      @table ||= JSON.parse(File.read(PATH)).freeze
    end
  end
end

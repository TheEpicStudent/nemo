module Fd
  class OutgoingFile
    SENDING_NOTE = "sending".freeze

    def self.queued_on(row)
      Array(row.files).map { |file| new(file) }
    end

    def initialize(file)
      @file = file || {}
    end

    def display_name
      @file["name"].presence || "attachment"
    end

    def note
      SENDING_NOTE
    end

    def stored?
      false
    end

    def image?
      false
    end
  end
end

module Fd
  class ThreadTranscript < ApplicationRecord
    self.table_name = "fd.thread_transcripts"

    KEY = /\A(?<channel_id>[CGD][A-Z0-9]{2,})_(?<thread_ts>\d{10,}\.\d{1,6})\z/

    scope :newest_first, -> { order(kept_at: :desc, id: :desc) }

    def self.for_key(key)
      match = KEY.match(key.to_s)
      return nil if match.nil?

      newest_first.find_by(channel_id: match[:channel_id], thread_ts: match[:thread_ts])
    end

    def readonly?
      persisted?
    end
  end
end

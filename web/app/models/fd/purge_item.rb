module Fd
  class PurgeItem < ApplicationRecord
    self.table_name = "fd.purge_items"
    self.primary_key = [:purge_id, :channel_id, :ts]

    belongs_to :purge, class_name: "Fd::ChannelPurge", foreign_key: :purge_id, inverse_of: :items

    def transcript_entry
      { "ts" => ts, "thread_ts" => thread_ts, "user" => author_id, "text" => text }
    end
  end
end

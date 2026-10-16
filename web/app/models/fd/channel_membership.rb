module Fd
  class ChannelMembership < ApplicationRecord
    self.table_name = "fd.channel_membership"
    self.primary_key = "channel_id"

    scope :joined, -> { where(inside: true) }

    def self.inside?(channel_id)
      return nil unless exists?

      joined.exists?(channel_id: channel_id)
    end

    def self.membership_for(channel_id)
      [inside?(channel_id), ChannelJoin.latest_for(channel_id)]
    end

    def readonly?
      persisted?
    end
  end
end

module Channels
  class Activity
    class Setting < ApplicationRecord
      self.table_name = "app.channel_message_activity"
      self.primary_key = "channel_id"
    end

    def self.visible?(channel_id) = Setting.where(channel_id: channel_id).exists?

    def self.visible_ids = Setting.pluck(:channel_id)
  end
end

module Fd
  class SlackUsergroup < ApplicationRecord
    self.table_name = "fd.slack_usergroups"
    self.primary_key = "usergroup_id"

    class Handles
      def [](usergroup_id)
        handles[usergroup_id]
      end

      private

      def handles
        @handles ||= SlackUsergroup.pluck(:usergroup_id, :handle).to_h
      end
    end
  end
end

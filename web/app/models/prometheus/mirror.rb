module Prometheus
  class Mirror
    def self.refresh(user_id)
      return false if user_id.blank?
      return false unless Roster.configured?

      settle(user_id, Roster.channels_for(user_id))
      true
    rescue Roster::Error, Roster::NotConfigured => e
      Rails.logger.warn("[prometheus] could not read #{user_id}: #{e.message}")
      false
    end

    def self.settle(user_id, channels)
      held = rows_for(user_id, channels)
      Appointment.transaction do
        Appointment.for_person(user_id).delete_all
        Appointment.insert_all!(held) if held.any?
      end
      Current.forget_roles
    end

    def self.rows_for(user_id, channels)
      seen_at = Time.current
      Array(channels).filter_map { |one| row_for(user_id, one, seen_at) }
        .uniq { |row| row[:channel_id] }
    end

    def self.row_for(user_id, said, seen_at)
      channel_id = said["channel_id"].to_s
      role = said["role"].to_s
      return nil if channel_id.blank? || Appointment::ROLES.exclude?(role)

      { user_id: user_id, channel_id: channel_id, role: role, seen_at: seen_at }
    end
  end
end

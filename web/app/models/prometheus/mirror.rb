module Prometheus
  class Mirror
    CHECK_TTL = 60.seconds

    def self.refresh_if_due(user_id)
      return false if user_id.blank?
      return false unless Roster.configured?
      return false unless Appointment.for_person(user_id).exists?
      return false unless check_due?(user_id)

      refresh(user_id)
    end

    def self.check_due?(user_id)
      key = "prometheus/checked/#{user_id}"
      return false if Rails.cache.read(key)

      Rails.cache.write(key, Time.current.to_i, expires_in: CHECK_TTL)
      true
    end

    def self.refresh(user_id)
      return false if user_id.blank?
      return false unless Roster.configured?

      replace_appointments(user_id, Roster.channels_for(user_id))
      true
    rescue Roster::Error, Roster::NotConfiguredError => e
      Rails.logger.warn("[prometheus] could not read #{user_id}: #{e.message}")
      false
    end

    def self.replace_appointments(user_id, channels)
      rows = rows_for(user_id, channels)
      Appointment.transaction do
        Appointment.for_person(user_id).delete_all
        Appointment.insert_all!(rows) if rows.any?
      end
      Current.forget_roles
    end

    def self.reconcile_all
      return false unless Roster.configured?

      rows = Roster.every_appointment.filter_map { |record| row_from(record) }.uniq { |row| row.values_at(:user_id, :channel_id) }
      return refuse_to_empty if rows.empty? && Appointment.exists?

      Appointment.transaction do
        Appointment.delete_all
        Appointment.insert_all!(rows) if rows.any?
      end
      Current.forget_roles
      rows.size
    rescue Roster::Error, Roster::NotConfiguredError => e
      Rails.logger.warn("[prometheus] reconcile stopped: #{e.message}")
      false
    end

    def self.refuse_to_empty
      Rails.logger.error(
        "[prometheus] the roster came back empty while #{Appointment.count} rows are held, " \
        "so nothing was changed"
      )
      false
    end

    def self.row_from(record)
      user_id = record["user_id"].to_s
      return nil if user_id.blank?

      row_for(user_id, record, Time.current)
    end

    def self.rows_for(user_id, channels)
      seen_at = Time.current
      Array(channels).filter_map { |record| row_for(user_id, record, seen_at) }
        .uniq { |row| row[:channel_id] }
    end

    def self.row_for(user_id, record, seen_at)
      channel_id = record["channel_id"].to_s
      role = record["role"].to_s
      return nil if channel_id.blank? || Appointment::ROLES.exclude?(role)

      { user_id: user_id, channel_id: channel_id, role: role, seen_at: seen_at }
    end
  end
end

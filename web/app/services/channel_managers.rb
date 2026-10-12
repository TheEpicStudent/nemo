class ChannelManagers
  TTL = 1.hour
  LOCK_TTL = 20.seconds
  METHOD = "admin.roles.listAssignments".freeze
  PAGE = 200
  PAGE_CAP = 20

  def self.role_id
    ENV["SLACK_CHANNEL_MANAGER_ROLE_ID"].presence
  end

  def self.for(channel_id)
    return [] if channel_id.blank?

    refresh_if_stale(channel_id)
    Api::ChannelManager.user_ids_in(channel_id)
  end

  def self.manages?(channel_id, user_id)
    self.for(channel_id).include?(user_id)
  end

  def self.swept_at(channel_id)
    Api::ChannelSweep.find_by(channel_id: channel_id)&.synced_at
  end

  def self.refresh_if_stale(channel_id)
    sweep = Api::ChannelSweep.find_by(channel_id: channel_id)

    return refresh(channel_id) if sweep.nil?
    return unless sweep.stale?(TTL)

    refresh(channel_id) if claim(channel_id)
  end

  def self.claim(channel_id)
    Rails.cache.write("channel_managers/lock/#{channel_id}", true,
      expires_in: LOCK_TTL, unless_exist: true)
  end

  def self.refresh(channel_id)
    assignments = fetch(channel_id)
    return if assignments.nil?

    store(channel_id, assignments)
  end

  def self.fetch(channel_id)
    return nil if role_id.nil?

    assignments = []
    cursor = nil
    PAGE_CAP.times do
      page = Slack::ProxyClient.call(METHOD,
        { role_ids: role_id, entity_ids: channel_id, limit: PAGE, cursor: cursor },
        credential: "admin")
      return nil unless page["ok"]

      Array(page["role_assignments"]).each do |row|
        next unless row["entity_id"] == channel_id && row["user_id"].present?

        assignments << [row["user_id"], row["date_create"]]
      end

      cursor = page.dig("response_metadata", "next_cursor").presence
      break if cursor.nil?
    end
    assignments
  rescue Slack::ProxyClient::Error, Slack::ProxyClient::NotConfiguredError => e
    Rails.logger.warn("channel_managers: #{e.class} for #{channel_id}")
    nil
  end

  def self.store(channel_id, assignments)
    Api::ChannelManager.transaction do
      Api::ChannelManager.where(channel_id: channel_id).delete_all
      Api::ChannelManager.insert_all(rows_for(channel_id, assignments)) if assignments.any?
      Api::ChannelSweep.stamp!(channel_id, assignments.size)
    end
  end

  def self.rows_for(channel_id, assignments)
    assignments.uniq { |user_id, _created_epoch| user_id }.map do |user_id, created_epoch|
      { channel_id: channel_id, user_id: user_id, assigned_at: created_epoch ? Time.zone.at(created_epoch) : nil }
    end
  end
end

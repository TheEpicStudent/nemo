module Fd
  class ChatPresence
    STALE_AFTER = 75.seconds
    CACHE_TTL = 10.minutes

    def self.join(case_id, user_id)
      change(case_id) do |entries|
        entry = entries.fetch(user_id, { "n" => 0 })
        entries[user_id] = { "n" => entry["n"] + 1, "at" => now }
      end
    end

    def self.heartbeat(case_id, user_id)
      change(case_id) do |entries|
        entry = entries.fetch(user_id, { "n" => 1 })
        entries[user_id] = { "n" => entry["n"], "at" => now }
      end
    end

    def self.leave(case_id, user_id)
      change(case_id) do |entries|
        remaining = entries.fetch(user_id, { "n" => 0 })["n"] - 1
        remaining.positive? ? entries[user_id] = { "n" => remaining, "at" => now } : entries.delete(user_id)
      end
    end

    def self.present_user_ids(case_id)
      active_entries(Rails.cache.read(key(case_id)) || {}).keys
    end

    def self.change(case_id)
      before = present_user_ids(case_id)
      entries = active_entries(Rails.cache.read(key(case_id)) || {})
      yield entries
      Rails.cache.write(key(case_id), entries, expires_in: CACHE_TTL)
      broadcast(case_id, entries.keys) if entries.keys.sort != before.sort
      entries.keys
    end

    def self.active_entries(entries)
      floor = now - STALE_AFTER.to_i
      entries.select { |_, entry| entry.is_a?(Hash) && entry["at"].to_i >= floor }
    end

    def self.now
      Time.current.to_i
    end

    def self.broadcast(case_id, user_ids)
      Turbo::StreamsChannel.broadcast_replace_to("case_#{case_id}_chat",
        target: "chat-presence-#{case_id}", partial: "fd/cases/presence",
        locals: { case_id: case_id, user_ids: user_ids, names: Names.for(user_ids) })
    end

    def self.key(case_id)
      "chat_presence/#{case_id}"
    end
  end
end

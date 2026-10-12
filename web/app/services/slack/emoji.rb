require "net/http"

module Slack
  class Emoji
    URL = "https://badger.hackclub.dev/api/emoji".freeze
    TTL = 12.hours
    MISSING_TTL = 1.hour
    OPEN_TIMEOUT = 5
    READ_TIMEOUT = 20
    ALIAS = "alias:".freeze
    HOPS = 3

    def self.for(names)
      requested = Array(names).map(&:to_s).reject(&:empty?).uniq
      return {} if requested.empty?

      emoji = requested.index_with { |name| Rails.cache.read(key_for(name)) }
      missing = requested.reject { |name| Rails.cache.exist?(key_for(name)) }
      emoji = emoji.merge(looked_up(missing)) if missing.any?
      emoji.compact
    end

    def self.key_for(name) = "slack/emoji/#{name}"

    def self.looked_up(missing)
      map = all
      return missing.index_with { nil } if map.nil?

      missing.index_with do |name|
        url = resolve(map, name)
        Rails.cache.write(key_for(name), url, expires_in: url ? TTL : MISSING_TTL)
        url
      end
    end

    def self.resolve(map, name)
      HOPS.times do
        value = map[name]
        return nil if value.blank?
        return value unless value.start_with?(ALIAS)

        name = value.delete_prefix(ALIAS)
      end
      nil
    end

    def self.all
      Rails.cache.fetch("slack/emoji/all", expires_in: TTL, skip_nil: true) { fetched }
    end

    def self.fetched
      uri = URI(URL)
      response = Net::HTTP.start(uri.host, uri.port, use_ssl: true,
                                 open_timeout: OPEN_TIMEOUT, read_timeout: READ_TIMEOUT) do |http|
        http.request(Net::HTTP::Get.new(uri))
      end
      return nil unless response.is_a?(Net::HTTPSuccess)

      parsed = JSON.parse(response.body)
      parsed.is_a?(Hash) ? parsed : nil
    rescue StandardError => e
      Rails.logger.warn("slack emoji list unavailable: #{e.message}")
      nil
    end
  end
end

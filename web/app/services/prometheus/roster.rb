require "net/http"

module Prometheus
  class Roster
    class Error < StandardError; end
    class Unavailable < Error; end
    class NotConfigured < StandardError; end

    OPEN_TIMEOUT = 2
    READ_TIMEOUT = 3

    CHANNELS = "/api/public/v1/users/%s/channels".freeze

    def self.configured?
      ENV["PROMETHEUS_BASE_URL"].present?
    end

    def self.channels_for(user_id)
      body = get(format(CHANNELS, CGI.escape(user_id.to_s)))
      return [] unless body["ok"]

      Array(body["channels"])
    end

    def self.get(path)
      uri = URI.join(base_url, path)
      response = Net::HTTP.start(uri.host, uri.port, use_ssl: uri.scheme == "https",
        open_timeout: OPEN_TIMEOUT, read_timeout: READ_TIMEOUT) do |http|
        http.request(Net::HTTP::Get.new(uri))
      end
      raise Unavailable, "prometheus answered #{response.code}" unless response.is_a?(Net::HTTPSuccess)

      JSON.parse(response.body)
    rescue JSON::ParserError => e
      raise Unavailable, "prometheus sent something that is not json: #{e.message}"
    rescue Net::OpenTimeout, Net::ReadTimeout, SystemCallError, IOError, SocketError => e
      raise Unavailable, e.message
    end

    def self.base_url
      ENV["PROMETHEUS_BASE_URL"].presence ||
        raise(NotConfigured, "PROMETHEUS_BASE_URL is not set")
    end
  end
end

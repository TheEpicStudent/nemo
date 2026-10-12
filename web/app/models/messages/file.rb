module Messages
  class File
    METHOD = "files.read".freeze
    INLINE = %w[image/png image/jpeg image/gif image/webp].freeze
    FALLBACK = "application/octet-stream".freeze

    Result = Struct.new(:bytes, :kind, :name, :error, keyword_init: true)

    def self.listed(message)
      Array(message && message["files"]).select { |file| file["id"].present? }
    end

    def self.in(message, file_id)
      listed(message).find { |file| file["id"] == file_id }
    end

    def self.image?(file)
      INLINE.include?(file["mimetype"].to_s)
    end

    def self.bytes_of(file)
      body = Slack::ProxyClient.file(METHOD, { "url" => file["url_private"] })
      Result.new(bytes: body.bytes, kind: kind_for(file, body.kind), name: file["name"].presence)
    rescue Slack::ProxyClient::NotConfiguredError => e
      Rails.logger.error("slack file proxy is not configured: #{e.message}")
      Result.new(error: :not_configured)
    rescue Slack::ProxyClient::AuthError
      Result.new(error: :reauth)
    rescue Slack::ProxyClient::Error
      Result.new(error: :unavailable)
    end

    def self.kind_for(file, _reported_kind)
      image?(file) ? file["mimetype"] : FALLBACK
    end
  end
end

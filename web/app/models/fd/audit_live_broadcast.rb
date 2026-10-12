module Fd
  class AuditLiveBroadcast
    CHANNEL = "fd_audit_event".freeze
    STREAM = "audit_live".freeze
    ACTION = "audit_event".freeze

    def self.relay(payload)
      content = stream_tag(payload)
      Turbo::StreamsChannel.broadcast_stream_to(STREAM, content: content) if content
    end

    def self.stream_tag(payload)
      event = JSON.parse(payload.to_s)
      return nil unless event.is_a?(Hash)

      %(<turbo-stream action="#{ACTION}" payload="#{ERB::Util.html_escape(event.to_json)}"></turbo-stream>).html_safe
    rescue JSON::ParserError
      nil
    end
  end
end

module Fd
  class Outgoing
    Sent = Struct.new(:queued, :problem, keyword_init: true)

    REPORTER_CLOSED = "Reporter conversation closed".freeze

    def self.queue(conversation, body, mode:, by:, conversation_selected: false)
      problem = validation_error(conversation, body, conversation_selected: conversation_selected)
      return Sent.new(problem: problem) if problem

      Sent.new(queued: IntakeOutbox.create!(conversation_id: conversation.id, kind: "reply",
        body: body, mode: mode, requested_by: by))
    end

    def self.validation_error(conversation, body, conversation_selected: false)
      return "Enter a message" if body.blank?
      if body.length > IntakeOutbox::MAX_LENGTH
        return "Keep it under #{IntakeOutbox::MAX_LENGTH} characters"
      end
      if conversation.nil?
        return conversation_selected ? REPORTER_CLOSED : "No reporter to reply to"
      end
      return "Conversation closed" if conversation.closed?

      nil
    end
  end
end

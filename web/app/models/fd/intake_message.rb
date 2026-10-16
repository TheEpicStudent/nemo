module Fd
  class IntakeMessage < ApplicationRecord
    self.table_name = "fd.intake_messages"

    TAIL_LIMIT = 50

    belongs_to :conversation, class_name: "Fd::IntakeConversation",
      foreign_key: :conversation_id, inverse_of: nil

    scope :oldest_first, -> { order(:posted_at, :id) }
    scope :newest_first, -> { order(posted_at: :desc, id: :desc) }
    scope :inbound, -> { where(direction: "inbound") }
    scope :outbound, -> { where(direction: "outbound") }
    scope :human_authored, -> { where(direction: "inbound").or(where.not(sent_by: nil)) }

    def self.count_for(conversation_ids)
      return 0 if conversation_ids.blank?

      where(conversation_id: conversation_ids).human_authored.count
    end

    def self.tail(conversation_ids, limit: TAIL_LIMIT)
      return [] if conversation_ids.blank?

      where(conversation_id: conversation_ids).human_authored
        .newest_first.limit(limit).to_a.reverse
    end

    def theirs?
      direction == "inbound"
    end

    def deleted?
      deleted_at.present?
    end

    def edited?
      edited_at.present?
    end
  end
end

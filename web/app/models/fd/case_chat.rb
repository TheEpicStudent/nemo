module Fd
  class CaseChat < ApplicationRecord
    self.table_name = "fd.case_chat"

    MAX_LENGTH = 4_000
    TAIL_LIMIT = 50

    scope :oldest_first, -> { order(:posted_at, :id) }
    scope :newest_first, -> { order(posted_at: :desc, id: :desc) }

    def self.tail(case_id, limit: TAIL_LIMIT)
      where(case_id: case_id).newest_first.limit(limit).to_a.reverse
    end

    def self.earlier_than(case_id, visible_count)
      [where(case_id: case_id).count - visible_count, 0].max
    end

    def deleted?
      deleted_at.present?
    end

    def edited?
      edited_at.present?
    end

    def from_slack?
      ts.present?
    end
  end
end

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

    def self.roots_for(cases)
      rooted = cases.select { |kase| kase.card_channel_id.present? && kase.card_thread_ts.present? }
      return {} if rooted.empty?

      lines = where(channel_id: rooted.map(&:card_channel_id).uniq, ts: rooted.map(&:card_thread_ts).uniq)
        .index_by { |line| [line.channel_id, line.ts] }
      rooted.each_with_object({}) do |kase, roots|
        line = lines[[kase.card_channel_id, kase.card_thread_ts]]
        roots[kase.id] = line if line
      end
    end

    def self.root_for(kase, family_ids = kase.family_ids)
      roots = roots_for(Case.where(id: family_ids).to_a)
      roots[kase.id] || roots.values.min_by(&:posted_at)
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

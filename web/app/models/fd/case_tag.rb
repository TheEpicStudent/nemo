module Fd
  class CaseTag < ApplicationRecord
    self.table_name = "fd.case_tags"
    self.primary_key = [:case_id, :tag_id]

    MAX_PER_CASE = 10

    belongs_to :kase, class_name: "Fd::Case", foreign_key: :case_id, inverse_of: :case_tags
    belongs_to :tag, class_name: "Fd::Tag", foreign_key: :tag_id, inverse_of: :case_tags

    validates :tag_id, uniqueness: { scope: :case_id, message: "That case already has this tag." }
    validate :room_on_case, on: :create

    scope :oldest_first, -> { order(:added_at, :tag_id) }

    private

    def room_on_case
      return if self.class.where(case_id: case_id).count < MAX_PER_CASE

      errors.add(:base, "A case holds up to #{MAX_PER_CASE} tags.")
    end
  end
end

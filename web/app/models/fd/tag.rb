module Fd
  class Tag < ApplicationRecord
    self.table_name = "fd.tags"

    NAME_LENGTH = 40
    NAME_SHAPE = /\A[a-z0-9]+(-[a-z0-9]+)*\z/

    has_many :case_tags, class_name: "Fd::CaseTag", foreign_key: :tag_id,
      inverse_of: :tag, dependent: nil
    has_many :cases, through: :case_tags, source: :kase

    before_validation { self.name = self.class.normalise(name) }

    validates :name, presence: { message: "Enter a tag" },
      length: { maximum: NAME_LENGTH, message: "Keep it under #{NAME_LENGTH} characters" },
      format: { with: NAME_SHAPE, allow_blank: true, message: "Letters, numbers and hyphens only" },
      uniqueness: { message: "Tag already exists" }

    scope :with_uses, -> {
      left_joins(:case_tags).group(:id).select(
        "fd.tags.*", "COUNT(fd.case_tags.tag_id) AS uses", "MAX(fd.case_tags.added_at) AS last_used_at"
      )
    }

    def self.normalise(value)
      value.to_s.downcase.gsub(/[^a-z0-9]+/, "-").delete_prefix("-").delete_suffix("-")
    end

    def merge_into!(target)
      transaction do
        target_case_ids = CaseTag.where(tag_id: target.id).select(:case_id)
        CaseTag.where(tag_id: id).where.not(case_id: target_case_ids).update_all(tag_id: target.id)
        CaseTag.where(tag_id: id).delete_all
        destroy!
      end
    end

    def self.find_or_add!(name, by:)
      normalised = normalise(name)
      find_by(name: normalised) ||
        transaction(requires_new: true) { create!(name: normalised, created_by: by) }
    rescue ActiveRecord::RecordNotUnique
      find_by!(name: normalised)
    end
  end
end

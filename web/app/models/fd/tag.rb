module Fd
  class Tag < ApplicationRecord
    self.table_name = "fd.tags"

    NAME_LENGTH = 40
    NAME_SHAPE = /\A[a-z0-9]+(-[a-z0-9]+)*\z/

    has_many :case_tags, class_name: "Fd::CaseTag", foreign_key: :tag_id,
      inverse_of: :tag, dependent: nil
    has_many :cases, through: :case_tags, source: :kase

    before_validation { self.name = self.class.normalise(name) }

    validates :name, presence: { message: "Type a tag." },
      length: { maximum: NAME_LENGTH, message: "Tags run to #{NAME_LENGTH} characters." },
      format: { with: NAME_SHAPE, allow_blank: true, message: "Use letters, numbers and hyphens." },
      uniqueness: { message: "That tag already exists." }

    def self.normalise(value)
      value.to_s.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\A-+|-+\z/, "")
    end

    def self.find_or_add!(name, by:)
      normalised = normalise(name)
      find_by(name: normalised) || create!(name: normalised, created_by: by)
    rescue ActiveRecord::RecordNotUnique
      find_by!(name: normalised)
    end
  end
end

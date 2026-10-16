module Fd
  class InfractionCategory < ApplicationRecord
    self.table_name = "fd.infraction_categories"
    self.primary_key = "key"

    scope :ordered, -> { order(:position, :key) }

    def self.all_ordered = Current.categories ||= ordered.to_a

    def self.labels = all_ordered.to_h { |category| [category.key, category.label] }

    def self.active_keys = all_ordered.reject(&:retired?).map(&:key)

    def self.label(key) = labels.fetch(key.to_s) { key.to_s.tr("_", " ") }

    def self.active_key?(key) = active_keys.include?(key.to_s)

    def self.known_key?(key) = labels.key?(key.to_s)

    def retired? = retired_at.present?
  end
end

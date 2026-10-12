module Fd
  module AuditCatalogue
    CATALOGUE = YAML.load_file(Rails.root.join("../db/audit_actions.yml")).freeze
    CATEGORIES = CATALOGUE.fetch("categories").freeze
    ACTIONS = CATALOGUE.fetch("actions").freeze

    def self.category_label(key) = CATEGORIES.fetch(key.to_s, key.to_s.tr("_", " "))

    def self.category_for(value)
      requested = value.to_s.strip.downcase
      CATEGORIES.find { |key, label| key == requested || label.downcase == requested }&.first
    end

    def self.action_label(action) = ACTIONS.dig(action.to_s, "label") || action.to_s.tr("_", " ")

    def self.actions_in(categories)
      ACTIONS.select { |_action, definition| categories.include?(definition["category"]) }.keys
    end

    def self.grouped(categories = CATEGORIES.keys)
      categories.map do |key|
        actions = ACTIONS.select { |_action, definition| definition["category"] == key }
          .sort_by { |_action, definition| definition["label"].to_s }.map(&:first)
        [key, category_label(key), actions]
      end
    end
  end
end

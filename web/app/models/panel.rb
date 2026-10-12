class Panel
  class UnknownError < ArgumentError; end

  PATH = Rails.root.join("../db/panels.yml").freeze
  ALL = YAML.load_file(PATH).fetch("panels").freeze

  def self.keys = ALL.keys

  def self.fetch(key)
    ALL.fetch(key.to_s) { raise UnknownError, "#{key} is not a panel" }
  end

  def self.label(key) = fetch(key).fetch("label")

  def self.needs(key) = fetch(key)["needs"]

  def self.open?(key) = needs(key).nil?

  def self.visible?(key, account)
    required_capability = needs(key)
    return account.present? if required_capability.nil?

    Authz.may?(account, required_capability)
  end

  def self.visible_to(account)
    keys.select { |key| visible?(key, account) }
  end
end

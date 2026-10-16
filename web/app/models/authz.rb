class Authz
  class UnknownError < ArgumentError; end

  PATH = Rails.root.join("../db/capabilities.yml").freeze
  TABLE = YAML.load_file(PATH).freeze

  CAPABILITIES = TABLE.fetch("capabilities").freeze
  ROLES = TABLE.fetch("roles").freeze
  AREAS = TABLE.fetch("areas").freeze
  SCOPES = TABLE.fetch("record_scopes").map(&:to_sym).freeze

  EFFECTIVE_CAPABILITY_SQL = "SELECT capability, via FROM app.effective_capability WHERE user_id = ?".freeze

  class << self
    def keys = CAPABILITIES.keys

    def fetch(key)
      CAPABILITIES.fetch(key.to_s) { raise UnknownError, "#{key} is not a capability" }
    end

    def label(key) = fetch(key).fetch("label")

    def area(key) = AREAS.fetch(fetch(key).fetch("area"))

    def record_scope(key) = fetch(key)["record_scope"]&.to_sym

    def scoped?(key) = record_scope(key).present?

    def logged?(key) = fetch(key)["logged"] == true

    def every_account?(key) = fetch(key)["every_account"] == true

    def locked?(key) = fetch(key)["locked"] == true

    def events(key) = fetch(key)["events"] || []

    def role_names = ROLES.keys

    def role_label(role) = ROLES.fetch(role.to_s).fetch("label")

    def grantable_roles = ROLES.select { |_, definition| definition.fetch("grantable", true) }.keys

    def superadmin?(role) = ROLES.fetch(role.to_s, {})["everything"] == true

    def baseline(role)
      definition = ROLES.fetch(role.to_s, {})
      return keys if definition["everything"]

      definition["capabilities"] || []
    end

    def by_area
      keys.group_by { |key| area(key) }
    end

    EFFECTIVE_ROLE_SQL = "SELECT role FROM app.effective_role WHERE user_id = ? ORDER BY role".freeze

    CAPABILITY_HOLDERS_SQL = "SELECT DISTINCT user_id FROM app.effective_capability " \
                             "WHERE capability = ? ORDER BY user_id".freeze

    def effective_capabilities(user_id)
      return {} if user_id.blank?

      cache = Current.effective_capabilities ||= {}
      cache[user_id] ||= load_effective_capabilities(user_id)
    end

    def effective_roles(user_id)
      return [] if user_id.blank?

      cache = Current.effective_roles ||= {}
      cache[user_id] ||= ApplicationRecord.connection
        .select_values(ApplicationRecord.sanitize_sql([EFFECTIVE_ROLE_SQL, user_id]))
    end

    def role?(account, role)
      return false if account.nil?

      effective_roles(account.user_id).include?(role.to_s)
    end

    def everything?(account)
      return false if account.nil?

      effective_roles(account.user_id).any? { |role| superadmin?(role) }
    end

    def anything?(account)
      return false if account.nil?

      effective_roles(account.user_id).any? || effective_capabilities(account.user_id).any?
    end

    def holders_of(key)
      ApplicationRecord.connection.select_values(
        ApplicationRecord.sanitize_sql([CAPABILITY_HOLDERS_SQL, key.to_s])
      )
    end

    def holds?(account, key)
      return false if account.nil?
      return true if every_account?(key)

      effective_capabilities(account.user_id).key?(key.to_s)
    end

    def via(account, key)
      return nil if account.nil?

      effective_capabilities(account.user_id)[key.to_s]
    end

    def may?(account, key, record = nil)
      return false unless holds?(account, key)

      within_scope?(account, key, record)
    end

    def within_scope?(account, key, record)
      scope = record_scope(key)
      return true if scope.nil? || record.nil?

      case scope
      when :author then record.respond_to?(:author) && record.author == account.user_id
      when :channel then Channels::Audience.may_see?(account, record)
      else false
      end
    end

    def why_not(account, key, record = nil)
      return nil if may?(account, key, record)
      return "No access" if account.nil? || effective_capabilities(account.user_id).empty?
      return refusal(key) unless holds?(account, key)

      "Not permitted"
    end

    def refusal(key)
      label = label(key).downcase
      standard_roles, superadmin_roles = role_names.partition { |role| !superadmin?(role) }
      granting_roles = standard_roles.select { |role| baseline(role).include?(key) }
      granting_roles = superadmin_roles.select { |role| baseline(role).include?(key) } if granting_roles.empty?
      return "#{label} is not permitted" if granting_roles.empty?

      "#{label} is #{granting_roles.map { |role| role_label(role) }.to_sentence} only"
    end

    def load_effective_capabilities(user_id)
      rows = ApplicationRecord.connection.select_all(
        ApplicationRecord.sanitize_sql([EFFECTIVE_CAPABILITY_SQL, user_id])
      )
      rows.to_h { |row| [row["capability"], row["via"]] }
    end
  end
end

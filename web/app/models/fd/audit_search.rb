module Fd
  class AuditSearch
    Term = Struct.new(:kind, :value, :label, :hint, keyword_init: true) do
      def to_s = "#{kind}:#{value}"
    end

    MEMBER = /\A[UW][A-Z0-9]{2,}\z/i
    CHANNEL = /\A[CGD][A-Z0-9]{2,}\z/i
    IPV4 = %r{\A\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?\z}
    IPV6 = %r{\A[0-9a-f]{0,4}(:[0-9a-f]{0,4}){2,7}(/\d{1,3})?\z}i
    EMAIL = /\A[^@\s]+@[^@\s]+\.[^@\s]+\z/
    DOMAIN = /\A[a-z0-9-]+(\.[a-z0-9-]+)+\z/i
    DATE = /\A\d{4}-\d{2}-\d{2}\z/

    KINDS = %w[actor about ip action category channel email domain source is show text
               before after last app session network country].freeze

    OPERATORS = {
      "actor" => "actor", "by" => "actor", "who" => "actor",
      "about" => "about", "to" => "about", "subject" => "about",
      "ip" => "ip", "from" => "ip", "address" => "ip",
      "action" => "action", "did" => "action", "verb" => "action",
      "category" => "category",
      "show" => "show",
      "in" => "channel", "channel" => "channel",
      "email" => "email", "domain" => "domain",
      "source" => "source",
      "is" => "is",
      "before" => "before", "after" => "after", "since" => "after",
      "last" => "last", "within" => "last",
      "app" => "app", "session" => "session",
      "network" => "network", "net" => "network",
      "country" => "country", "cc" => "country"
    }.freeze

    NETWORKS = { "stable" => "Stable", "rotating" => "Rotating", "vpn" => "VPN",
                 "hosting" => "Hosting", "tor" => "Tor" }.freeze
    COUNTRY = /\A[a-z]{2}\z/i

    SOURCES = %w[engine slack read fire_engine].freeze
    ACTOR_TYPES = %w[nemo human nobody].freeze

    QUALIFIED = /\A([a-z_]+):(.+)\z/i

    def self.parse(query, actor: nil)
      new(query, actor: actor)
    end

    def initialize(query, actor: nil)
      @query = query.to_s
      @actor = actor
    end

    attr_reader :actor

    def any? = terms.any?

    def terms
      @terms ||= tokens.filter_map { |token| term_for(token) }
    end

    def of(kind)
      terms.select { |term| term.kind == kind }.map(&:value)
    end

    def first_value(kind) = of(kind).first

    def text = of("text").join(" ")

    def text? = text.length >= 2

    def without(term)
      remaining = terms.reject { |existing| existing.kind == term.kind && existing.value == term.value }
      remaining.map { |existing| label_for(existing) }.join(" ")
    end

    def label_for(term)
      return term.value if term.kind == "text"

      "#{term.kind}:#{term.value}"
    end

    def to_s = terms.map { |term| label_for(term) }.join(" ")

    def since
      window = first_value("last")
      return nil if window.nil?

      count = window.to_i
      window.end_with?("h") ? count.hours.ago : (Date.current - (count - 1)).in_time_zone
    end

    def identity?
      return @identity if defined?(@identity)

      @identity = actor.present? && actor.may?("identity.read")
    end

    IDENTITY_KINDS = %w[ip email domain].freeze
    IDENTITY_TEXT = /\d{1,3}(?:\.\d{1,3}){3}|[^@\s":]+@[^@\s":]+\.[a-z]|\h{1,4}:\h{0,4}:/i

    def identity_terms?
      return true if IDENTITY_KINDS.any? { |kind| of(kind).any? }

      of("text").any? { |value| value.match?(IDENTITY_TEXT) }
    end

    def member_ids_for_email
      return @member_ids_for_email if defined?(@member_ids_for_email)

      emails = of("email").map(&:downcase)
      domains = of("domain").map(&:downcase)
      @member_ids_for_email =
        if !identity? || (emails.empty? && domains.empty?)
          []
        else
          MemberIdentity.kept.where(email_condition(emails, domains)).pluck(:user_id)
        end
    end

    def member_ids_for_ip
      return @member_ids_for_ip if defined?(@member_ids_for_ip)

      addresses = of("ip")
      @member_ids_for_ip =
        addresses.empty? ? [] : LoginEvent.addressed.where(ip_condition(addresses)).distinct.pluck(:user_id)
    end

    private

    def email_condition(emails, domains)
      parts = []
      binds = {}
      if emails.any?
        parts << "lower(email) IN (:emails)"
        binds[:emails] = emails
      end
      if domains.any?
        parts << "lower(split_part(email, '@', 2)) IN (:domains)"
        binds[:domains] = domains
      end
      [parts.join(" OR "), binds]
    end

    def ip_condition(addresses)
      parts = addresses.map { |query| query.include?("/") ? "ip << ?::inet" : "ip = ?::inet" }
      [parts.join(" OR "), *addresses]
    end

    QUOTED = /"([^"]*)"|(\S+)/

    def tokens
      @tokens ||= @query.scan(QUOTED).map { |quoted, bare| quoted || bare }.reject(&:blank?)
    end

    def term_for(token)
      match = QUALIFIED.match(token)
      return qualified_term(match[1].downcase, match[2]) if match && OPERATORS.key?(match[1].downcase)

      inferred_term(token)
    end

    def qualified_term(operator, query)
      kind = OPERATORS.fetch(operator)
      value = query.strip.delete_prefix("@").delete_prefix("#")
      return nil if value.blank?

      case kind
      when "actor", "about" then member_term(kind, value)
      when "channel" then channel_term(value)
      when "source" then source_term(value)
      when "category" then category_term(value)
      when "show" then show_term(value)
      when "is" then actor_type_term(value)
      when "before", "after" then time_term(kind, value)
      when "last" then window_term(value)
      when "app" then app_term(value)
      when "network" then network_term(value)
      when "country" then country_term(value)
      when "session" then session_term(value)
      when "domain" then email_term("domain", value)
      when "email" then email_term("email", value)
      else Term.new(kind: kind, value: value, label: "#{operator} #{value}")
      end
    end

    def inferred_term(token)
      query = token.strip
      return nil if query.blank?

      return member_term("about", query.delete_prefix("@")) if query.start_with?("@")
      return channel_term(query.delete_prefix("#")) if query.start_with?("#")
      return Term.new(kind: "ip", value: query, label: query) if address?(query)
      return member_term("about", query) if query.match?(MEMBER)
      return channel_term(query) if query.match?(CHANNEL)
      return Term.new(kind: "email", value: query, label: query) if query.match?(EMAIL)
      return time_term("after", query) if query.match?(DATE)

      Term.new(kind: "text", value: query, label: query)
    end

    def address?(query)
      query.match?(IPV4) || (query.include?(":") && query.match?(IPV6))
    end

    def member_term(kind, query)
      return Term.new(kind: kind, value: actor.user_id, label: "#{kind} me", hint: actor.user_id) if
        query.casecmp?("me") && actor&.user_id.present?

      user_id = query.match?(MEMBER) ? query.upcase : by_handle(query)
      return Term.new(kind: "text", value: query, label: query) if user_id.nil?

      Term.new(kind: kind, value: user_id, label: "#{kind} #{query}", hint: user_id)
    end

    def by_handle(query)
      Member.where("lower(handle) = :query OR lower(display_name) = :query", query: query.downcase)
        .limit(1).pick(:user_id)
    end

    def channel_term(query)
      channel_id = query.match?(CHANNEL) ? query.upcase : by_channel_name(query)
      return Term.new(kind: "text", value: query, label: query) if channel_id.nil?

      Term.new(kind: "channel", value: channel_id, label: "in #{query}", hint: channel_id)
    end

    def by_channel_name(query)
      Analytics::DimChannel.where("lower(name) = ?", query.downcase).limit(1).pick(:channel_id)
    end

    def email_term(kind, query)
      normalized = query.downcase
      return Term.new(kind: "domain", value: normalized.split("@").last, label: "domain #{normalized.split('@').last}") if
        kind == "domain" && normalized.include?("@")
      return Term.new(kind: "domain", value: normalized, label: "domain #{normalized}") if
        kind == "email" && !normalized.include?("@") && normalized.match?(DOMAIN)

      Term.new(kind: kind, value: normalized, label: "#{kind} #{normalized}")
    end

    SHOW_VALUES = { "high_volume" => "high_volume", "high-volume" => "high_volume", "busy" => "high_volume" }.freeze

    def show_term(query)
      value = SHOW_VALUES[query.downcase]
      return nil if value.nil?

      Term.new(kind: "show", value: value, label: "high-volume actions")
    end

    def category_term(query)
      key = AuditCatalogue.category_for(query)
      return nil if key.nil?

      Term.new(kind: "category", value: key, label: AuditCatalogue.category_label(key))
    end

    def actor_type_term(query)
      actor_type = query.downcase
      actor_type = "human" if actor_type == "person"
      return nil unless ACTOR_TYPES.include?(actor_type)

      Term.new(kind: "is", value: actor_type, label: "actor type #{actor_type}")
    end

    def source_term(query)
      source = query.downcase
      source = "fire_engine" if source == "engine"
      return nil unless SOURCES.include?(source)

      Term.new(kind: "source", value: source, label: "source #{query}")
    end

    TIMESTAMP = /\A\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/
    MINUTE = "%Y-%m-%dT%H:%M".freeze

    def time_term(kind, query)
      at = Time.zone.parse(query)
      return nil if at.nil?

      value = query.match?(TIMESTAMP) ? at.strftime(MINUTE) : at.to_date.iso8601
      Term.new(kind: kind, value: value, label: "#{kind} #{value.tr('T', ' ')}")
    rescue ArgumentError
      nil
    end

    def network_term(query)
      network_class = query.downcase
      return nil unless NETWORKS.key?(network_class)

      Term.new(kind: "network", value: network_class, label: "network #{NETWORKS.fetch(network_class)}")
    end

    def country_term(query)
      return nil unless query.match?(COUNTRY)

      Term.new(kind: "country", value: query.upcase, label: "country #{query.upcase}")
    end

    APP = /\A[AB][A-Z0-9]{2,}\z/i

    def app_term(query)
      return nil unless query.match?(APP)

      Term.new(kind: "app", value: query.upcase, label: "app #{query.upcase}")
    end

    SESSION = /\A\d{1,19}\z/

    def session_term(query)
      return nil unless query.match?(SESSION)

      Term.new(kind: "session", value: query, label: "session #{query}")
    end

    WINDOW = /\A(\d{1,3})(h|d)\z/i
    UNITS = { "h" => "hour", "d" => "day" }.freeze

    def window_term(query)
      match = WINDOW.match(query.delete(" "))
      return nil if match.nil? || match[1].to_i.zero?

      count = match[1].to_i
      unit = UNITS.fetch(match[2].downcase)
      Term.new(kind: "last", value: "#{count}#{match[2].downcase}",
        label: "last #{count == 1 ? unit : "#{count} #{unit.pluralize}"}")
    end
  end
end

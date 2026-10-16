module Fd
  class BlockedDomain < ApplicationRecord
    self.table_name = "fd.blocked_domains"

    EXACT = "exact".freeze
    SUFFIX = "suffix".freeze
    MATCHES = [EXACT, SUFFIX].freeze

    FLAG = "flag".freeze
    HOLD = "hold".freeze
    DEACTIVATE = "deactivate".freeze
    EFFECTS = [FLAG, HOLD, DEACTIVATE].freeze
    SHIPPED_EFFECTS = [FLAG].freeze

    SHAPE = /\A[a-z0-9-]+(\.[a-z0-9-]+)+\z/
    TOO_MANY = 0.005

    scope :active, -> { where(active: true) }
    scope :retired, -> { where(active: false) }
    scope :newest_first, -> { order(added_at: :desc, id: :desc) }

    def self.active_listed = active.newest_first.to_a

    def self.add!(domain:, by:, match_mode: EXACT, effect: FLAG, note: nil)
      create!(domain: domain.to_s.strip.downcase.delete_prefix("@"),
        match_mode: match_mode, effect: effect, note: note.presence, added_by: by)
    end

    def self.matching_rules(domain)
      text = domain.to_s.strip.downcase
      return [] if text.blank?

      active.select { |rule| rule.matches?(text) }
    end

    def self.strictest_for(domain)
      matching_rules(domain).max_by { |rule| EFFECTS.index(rule.effect) }
    end

    def self.valid_domain?(text)
      text.to_s.strip.downcase.delete_prefix("@").match?(SHAPE)
    end

    def self.account_count_on(domain, match_mode: EXACT)
      text = domain.to_s.strip.downcase
      scope = MemberIdentity.unpurged.where.not(email: nil)
      return scope.where("lower(split_part(email, '@', 2)) = ?", text).count if
        match_mode == EXACT

      scope.where("lower(split_part(email, '@', 2)) = ? OR " \
                  "lower(split_part(email, '@', 2)) LIKE ?", text, "%.#{text}").count
    end

    def self.too_many?(count)
      known = MemberIdentity.unpurged.where.not(email: nil).count
      return false if known.zero?

      count.to_f / known > TOO_MANY
    end

    def matches?(text)
      return text == domain if match_mode == EXACT

      text == domain || text.end_with?(".#{domain}")
    end

    def retire!(by:)
      update!(active: false, retired_at: Time.current, retired_by: by)
    end

    def retired? = !active

    def shipped? = SHIPPED_EFFECTS.include?(effect)

    def account_count
      @account_count ||= self.class.account_count_on(domain, match_mode: match_mode)
    end

    def referenced_user_ids = [added_by, retired_by].compact
  end
end

require "securerandom"

module Api
  class Token < ApplicationRecord
    self.table_name = "api.token"

    KEY_PREFIX = "nemo_live_".freeze
    ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz".chars.freeze
    LENGTH = 20
    PREFIX_SECRET_CHARS = 4
    MAX_NAME = 60

    class KeyLimitError < StandardError; end
    class NotApprovedError < StandardError; end

    belongs_to :app, class_name: "Api::App", foreign_key: :app_id, inverse_of: :tokens

    LIFETIMES = {
      "30" => 30.days,
      "90" => 90.days,
      "365" => 365.days,
      "never" => nil
    }.freeze

    LIFETIME_LABELS = {
      "30" => "30 days",
      "90" => "90 days",
      "365" => "a year",
      "never" => "no expiry"
    }.freeze

    DEFAULT_LIFETIME = "90".freeze

    scope :live, lambda {
      where(revoked_at: nil).where("expires_at IS NULL OR expires_at > now()")
    }

    def self.for_owner(user_id)
      where(owner_user_id: user_id).order(revoked_at: :asc, created_at: :desc)
    end

    def self.for_app(app_id)
      where(app_id: app_id).order(revoked_at: :asc, created_at: :desc)
    end

    def self.below_limit?(app_id)
      live.where(app_id: app_id).count < Setting.value("tokens_per_owner")
    end

    def self.digest_of(secret)
      Digest::SHA256.hexdigest(secret.to_s)
    end

    def self.secret
      KEY_PREFIX + Array.new(LENGTH) { ALPHABET[SecureRandom.random_number(ALPHABET.size)] }.join
    end

    def self.life_for(requested)
      LIFETIMES.key?(requested.to_s) ? requested.to_s : DEFAULT_LIFETIME
    end

    def self.expires_on(requested)
      span = LIFETIMES.fetch(life_for(requested))
      span && span.from_now
    end

    def self.mint!(app, name, lifetime: DEFAULT_LIFETIME)
      raise NotApprovedError unless Approval.active?(app.id)
      raise KeyLimitError unless below_limit?(app.id)

      key = secret
      row = create!(app_id: app.id, owner_user_id: app.owner_user_id,
        name: name.to_s.strip.first(MAX_NAME),
        prefix: key.first(KEY_PREFIX.length + PREFIX_SECRET_CHARS), digest: digest_of(key),
        expires_at: expires_on(lifetime))
      [row, key]
    end

    LAST_USED_RESOLUTION = 1.minute

    def revoked? = revoked_at.present?

    def expired? = expires_at.present? && expires_at <= Time.current

    def inactive? = revoked? || expired?

    def used!
      return if last_used_at && last_used_at > LAST_USED_RESOLUTION.ago

      update_column(:last_used_at, Time.current)
    end

    def revoke!(by:)
      update!(revoked_at: Time.current, revoked_by: by)
    end

    def rotate!(by:)
      key = self.class.secret
      update!(prefix: key.first(KEY_PREFIX.length + PREFIX_SECRET_CHARS), digest: self.class.digest_of(key),
        rotated_at: Time.current)
      Event.record!("token_rotated", actor: by, subject: display_prefix, detail: name)
      key
    end

    def rate
      rate_limit || Setting.value("rate_per_minute")
    end

    def display_prefix
      "#{prefix}…"
    end

    def expires_in_label
      return "never" if expires_at.nil?
      return "expired" if expired?

      "#{((expires_at - Time.current) / 1.day).ceil}d"
    end
  end
end

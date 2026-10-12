module Fd
  class StaffSlack < ApplicationRecord
    self.table_name = "fd.staff_slack"
    self.primary_key = "staff_user_id"

    encrypts :user_token

    SCOPE = "chat:write".freeze
    SLACK = "slack".freeze
    REVOKED_ERRORS = %w[token_revoked invalid_auth account_inactive not_authed].freeze

    scope :live, -> { where(revoked_at: nil) }

    def self.active_for(user_id)
      live.find_by(staff_user_id: user_id)
    end

    def self.store!(user_id, token:, team_id:, scopes:)
      row = find_or_initialize_by(staff_user_id: user_id)
      row.update!(user_token: token, team_id: team_id, scopes: scopes,
        granted_at: Time.current, last_used_at: nil, last_error: nil, last_error_at: nil,
        revoked_at: nil, revoked_by: nil)
      row
    end

    def live?
      revoked_at.nil?
    end

    def errored?
      last_error.present?
    end

    def used!
      update_columns(last_used_at: Time.current, last_error: nil, last_error_at: nil)
    end

    def record_error!(message)
      return mark_revoked!(message) if REVOKED_ERRORS.include?(message.to_s)

      update_columns(last_error: message.to_s.first(200), last_error_at: Time.current)
    end

    def mark_revoked!(message)
      update_columns(last_error: message.to_s.first(200), last_error_at: Time.current,
        revoked_at: Time.current, revoked_by: SLACK)
    end

    def revoked_by_slack?
      revoked_by == SLACK
    end

    def return_token!(by)
      update!(revoked_at: Time.current, revoked_by: by)
    end
  end
end

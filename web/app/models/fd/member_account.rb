module Fd
  class MemberAccount < ApplicationRecord
    self.table_name = "fd.member_account"
    self.primary_key = "user_id"

    SIGN_INS_FROM = AuditQuery::FIRST_DAY

    STATES = {
      "deactivated" => "Deactivated",
      "invite_pending" => "Invite pending",
      "claimed_no_sign_in" => "Claimed, no sign-in",
      "active" => "Active"
    }.freeze

    def readonly? = true

    def state
      return "deactivated" if deactivated
      return "invite_pending" if invite_pending
      return nil if claimed_at.nil?
      return "active" if last_login_at || last_post_at

      claimed_at >= SIGN_INS_FROM.in_time_zone ? "claimed_no_sign_in" : nil
    end

    def state_label = STATES[state]
  end
end

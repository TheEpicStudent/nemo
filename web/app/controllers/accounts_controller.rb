class AccountsController < ApplicationController
  WINDOW = 30.days
  AUDIT_ROW_LIMIT = 10

  def show
    @account = Fd::StaffSlack.find_by(staff_user_id: current_account.user_id)
    @linkable = Slack::Oauth.configured? && current_account.may?("slack.link")
    @roles = Authz.effective_roles(current_account.user_id)
    @has_access = @roles.any? || Authz.effective_capabilities(current_account.user_id).any?

    audit_rows = @has_access ? Fd::AuditTrail.new(current_account.user_id, since: WINDOW.ago).rows : []
    @audit_row_count = audit_rows.size
    @audit_rows = audit_rows.first(AUDIT_ROW_LIMIT)

    @names = Fd::Names.for([current_account.user_id])
  end
end

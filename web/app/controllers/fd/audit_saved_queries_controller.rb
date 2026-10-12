module Fd
  class AuditSavedQueriesController < BaseController
    permit "case.read"

    def create
      saved = AuditSavedQuery.new(
        name: params[:name].to_s.strip, query: params[:query].to_s.strip, view: params[:view].presence,
        owner_user_id: params[:shared] == "1" ? nil : current_account.user_id,
        created_by: current_account.user_id
      )
      return redirect_with_alert(saved.errors.full_messages.to_sentence) unless saved.valid?

      writing do
        saved.save!
        audit(saved, "added", after: { "name" => saved.name, "query" => saved.query, "shared" => saved.shared? })
      end

      redirect_to fd_audit_path(saved.params), notice: "Saved #{saved.name}"
    end

    def destroy
      saved = AuditSavedQuery.find_by(id: params[:id])
      return redirect_with_alert("Not saved") if saved.nil?
      return redirect_with_alert("Only its author can remove it") unless saved.removable_by?(current_account)

      writing do
        saved.destroy!
        audit(saved, "removed", before: { "name" => saved.name, "query" => saved.query })
      end

      redirect_to fd_audit_path, notice: "Removed #{saved.name}"
    end

    private

    def redirect_with_alert(message)
      redirect_to fd_audit_path, alert: message
    end
  end
end

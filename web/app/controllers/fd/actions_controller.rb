module Fd
  class ActionsController < BaseController
    include LogsActions

    permit "case.act", on: -> { Case.find(params[:case_id]) }

    def create
      kase = Case.find(params[:case_id])
      lock = Action.from_thread_lock?(type_key) ? thread_lock : nil
      guard = lock ? nil : standing_guard

      error = guard ? standing_error(kase, guard) : action_error(kase)
      if error
        return redirect_to(fd_case_path(kase, do: "action"),
          alert: (error unless flash[:field_error]))
      end

      subject_added = false
      adopted = lock&.orphaned?
      echoed = nil
      writing do
        subject_added = add_target_subject(kase) unless lock
        if guard
          attach_standing(kase, guard)
        elsif lock
          audit(log_thread_lock(kase, lock), "performed")
        else
          action = log_action(kase, Time.current)
          audit(action, "performed")
          enforce(kase, action)
          echoed = ActionEcho.write!(kase, action, by: current_account.user_id)
        end
      end
      SlackPost.post_to_thread(echoed) if echoed&.mirrored_as == "user"

      redirect_to fd_case_path(kase, tab: "actions"),
        notice: notice_for(kase, guard: guard, lock: lock, adopted: adopted, subject_added: subject_added)
    end

    def update
      kase = Case.find(params[:case_id])
      action = Action.find_by(id: params[:id], case_id: kase.family_ids)
      return redirect_to(fd_case_path(kase, tab: "actions"), alert: "Action not found") if action.nil?

      error = edit_error(action)
      if error
        return redirect_to(fd_case_path(kase, tab: "actions", do: "edit-action-#{action.id}"),
          alert: (error unless flash[:field_error]))
      end

      action.assign_attributes(reason: params[:reason].to_s.strip.presence,
        category_key: params[:category_key].to_s.presence)
      return redirect_to(fd_case_path(kase, tab: "actions"), notice: "No changes") unless action.changed?

      writing do
        action.save!
        audit(action, "edited")
      end
      redirect_to fd_case_path(kase, tab: "actions"), notice: "Action updated"
    end

    private

    def edit_error(action)
      if params[:reason].to_s.strip.blank? && !action.from_thread_lock?
        return wrong!(:edit_reason, "Enter a reason", params[:reason])
      end

      category_key = params[:category_key].to_s
      if category_key.present? && category_key != action.category_key &&
          !InfractionCategory.active_key?(category_key)
        return "Select a category"
      end

      nil
    end

    def notice_for(kase, guard:, lock:, adopted:, subject_added:)
      return attached_notice(kase, guard) if guard
      return locked_notice(kase, adopted) if lock

      logged_notice(kase, subject_added)
    end

    def add_target_subject(kase)
      return false if target_user_id.blank?
      return false if kase.subject_user_ids.include?(target_user_id)

      ActiveRecord::Base.transaction(requires_new: true) do
        audit(kase.add_subject!(target_user_id), "attached", entity_id: kase.id)
      end
      true
    rescue ActiveRecord::RecordNotUnique
      false
    end

    def attached_notice(kase, guard)
      "the #{guard_label_text(guard)} already standing on @#{guard.subject_id} " \
        "is now on case #{kase.id}"
    end

    def locked_notice(kase, adopted)
      message = "thread lock logged on case #{kase.id}"
      adopted ? "#{message}, and the thread is now on this case" : message
    end

    def logged_notice(kase, subject_added)
      message = if kase.resolved?
        "#{type_name.downcase} logged on case #{kase.id}"
      else
        "#{type_name.downcase} logged, case #{kase.id} stays open"
      end
      subject_added ? "#{message}, and the case is now also about @#{target_user_id}" : message
    end
  end
end

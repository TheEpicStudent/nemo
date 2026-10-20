module Fd
  class CaseTagsController < BaseController
    permit "case.tag", on: -> { Case.find(params[:case_id]) }

    def create
      kase = Case.find(params[:case_id])
      name = Tag.normalise(params[:name])
      return redirect_to(fd_case_path(kase), alert: "Enter a tag") if name.blank?

      tag = nil
      writing do
        tag = Tag.find_or_add!(name, by: current_account.user_id)
        audit(tag, "added", after: { "name" => tag.name }) if tag.previously_new_record?
        link = kase.case_tags.create!(tag: tag, added_by: current_account.user_id)
        audit(link, "added", entity_id: kase.id, after: { "tag" => tag.name })
      end

      redirect_to fd_case_path(kase), notice: "#{tag.name} added to the case"
    rescue ActiveRecord::RecordInvalid => invalid
      redirect_to fd_case_path(kase), alert: invalid.record.errors.map(&:message).to_sentence
    rescue ActiveRecord::RecordNotUnique
      redirect_to fd_case_path(kase), alert: "Tag already on case"
    end

    def destroy
      kase = Case.find(params[:case_id])
      link = kase.case_tags.includes(:tag).find_by(tag_id: params[:id])
      return redirect_to(fd_case_path(kase), alert: "Tag not on case") if link.nil?

      writing do
        audit(link, "removed", entity_id: kase.id, before: { "tag" => link.tag.name }, after: nil)
        link.destroy!
      end

      flash[:action] = { "label" => "Undo", "href" => fd_case_tags_path(kase), "method" => "post",
                         "params" => { "name" => link.tag.name } }
      redirect_to fd_case_path(kase), notice: "#{link.tag.name} removed from the case"
    end
  end
end

module Fd
  class TagsController < BaseController
    PICKER_LIMIT = 8

    permit "app.configure", only: %i[update destroy merge]

    def search
      term = Tag.normalise(params[:q])
      tags = Tag.with_uses
      tags = tags.where.not(id: CaseTag.where(case_id: params[:case_id]).select(:tag_id)) if params[:case_id].present?
      tags = tags.where.not(name: params[:except]) if params[:except].present?
      tags = tags.where("fd.tags.name LIKE ?", "%#{Tag.sanitize_sql_like(term)}%") if term.present?
      rows = tags.order(Arel.sql("COUNT(fd.case_tags.tag_id) DESC, fd.tags.name")).limit(PICKER_LIMIT)

      items = rows.map { |tag| { id: tag.name, name: tag.name, uses: tag.uses } }
      items << { id: term, name: "Create \"#{term}\"", create: true } if creatable?(term)
      render json: { tags: items }
    end

    def update
      tag = Tag.find(params[:id])
      previous = tag.name
      return redirect_to(return_path, alert: "That is already its name.") if Tag.normalise(params[:name]) == previous

      writing do
        tag.update!(name: params[:name])
        audit(tag, "renamed", before: { "name" => previous }, after: { "name" => tag.name })
      end

      redirect_to return_path, notice: "#{previous} is now #{tag.name}"
    rescue ActiveRecord::RecordInvalid => invalid
      redirect_to return_path, alert: invalid.record.errors.map(&:message).to_sentence
    end

    def merge
      source = Tag.find(params[:id])
      target = Tag.find_by(name: Tag.normalise(params[:into]))
      return redirect_to(return_path, alert: "Pick a tag to merge into.") if target.nil?
      return redirect_to(return_path, alert: "Pick a different tag.") if target == source

      cases = source.case_tags.count
      writing do
        source.merge_into!(target)
        audit(target, "merged", before: { "tag" => source.name, "cases" => cases },
          after: { "into" => target.name })
      end

      redirect_to return_path, notice: "#{source.name} merged into #{target.name}"
    end

    def destroy
      tag = Tag.find(params[:id])
      if tag.case_tags.exists?
        return redirect_to(return_path, alert: "#{tag.name} is still on cases. Merge it instead.")
      end

      writing do
        audit(tag, "removed", before: { "name" => tag.name }, after: nil)
        tag.destroy!
      end

      redirect_to return_path, notice: "#{tag.name} removed"
    rescue ActiveRecord::InvalidForeignKey
      redirect_to return_path, alert: "#{tag.name} is still on cases. Merge it instead."
    end

    private

    def return_path = fd_configuration_path(tab: "tags")

    def creatable?(term)
      params[:create] != "0" && term.present? && term.length <= Tag::NAME_LENGTH &&
        !Tag.exists?(name: term)
    end
  end
end

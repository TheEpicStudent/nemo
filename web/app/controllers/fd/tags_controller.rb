module Fd
  class TagsController < BaseController
    PICKER_LIMIT = 8

    def search
      term = Tag.normalise(params[:q])
      tags = Tag.with_uses
      tags = tags.where.not(id: CaseTag.where(case_id: params[:case_id]).select(:tag_id)) if params[:case_id].present?
      tags = tags.where("fd.tags.name LIKE ?", "%#{Tag.sanitize_sql_like(term)}%") if term.present?
      rows = tags.order(Arel.sql("COUNT(fd.case_tags.tag_id) DESC, fd.tags.name")).limit(PICKER_LIMIT)

      items = rows.map { |tag| { id: tag.name, name: tag.name, uses: tag.uses } }
      items << { id: term, name: "Create \"#{term}\"", create: true } if creatable?(term)
      render json: { tags: items }
    end

    private

    def creatable?(term)
      term.present? && term.length <= Tag::NAME_LENGTH && !Tag.exists?(name: term)
    end
  end
end

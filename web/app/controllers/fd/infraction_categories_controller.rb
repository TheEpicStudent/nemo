module Fd
  class InfractionCategoriesController < BaseController
    permit "app.configure"

    def create
      label = params[:label].to_s.squish
      return redirect_to(return_path, alert: "Enter a label") if label.blank?

      category = nil
      writing do
        category = InfractionCategory.create!(key: InfractionCategory.key_for(label), label: label,
          position: InfractionCategory.next_position)
        audit(category, "added", after: { "key" => category.key, "label" => category.label })
      end

      redirect_to return_path, notice: "#{category.label} added"
    rescue ActiveRecord::RecordInvalid => invalid
      redirect_to return_path, alert: invalid.record.errors.full_messages.to_sentence
    end

    def update
      category = InfractionCategory.find(params[:key])
      previous = category.label
      label = params[:label].to_s.squish
      return redirect_to(return_path, alert: "Enter a label") if label.blank?
      return redirect_to(return_path) if label == previous

      writing do
        category.update!(label: label, updated_at: Time.current)
        audit(category, "renamed", before: { "label" => previous }, after: { "label" => label })
      end

      redirect_to return_path, notice: "#{previous} renamed to #{label}"
    rescue ActiveRecord::RecordInvalid => invalid
      redirect_to return_path, alert: invalid.record.errors.full_messages.to_sentence
    end

    def move
      category = InfractionCategory.find(params[:key])
      neighbour = neighbour_of(category, params[:direction].to_s)
      return redirect_to(return_path) if neighbour.nil?

      writing do
        position = category.position
        category.update!(position: neighbour.position, updated_at: Time.current)
        neighbour.update!(position: position, updated_at: Time.current)
        audit(category, "tuned", before: { "position" => position }, after: { "position" => category.position })
      end

      redirect_to return_path
    end

    def retire
      category = InfractionCategory.active.find(params[:key])
      writing do
        category.update!(retired_at: Time.current, updated_at: Time.current)
        audit(category, "retired", before: { "retired_at" => nil }, after: { "retired_at" => category.retired_at.iso8601 })
      end

      redirect_to return_path, notice: "#{category.label} retired"
    end

    def restore
      category = InfractionCategory.where.not(retired_at: nil).find(params[:key])
      writing do
        category.update!(retired_at: nil, updated_at: Time.current)
        audit(category, "restored", before: { "retired_at" => "set" }, after: { "retired_at" => nil })
      end

      redirect_to return_path, notice: "#{category.label} restored"
    end

    private

    def neighbour_of(category, direction)
      active = InfractionCategory.active.ordered.to_a
      index = active.index(category)
      return nil if index.nil?

      step = direction == "up" ? -1 : 1
      return nil if (index + step).negative?

      active[index + step]
    end

    def return_path = fd_configuration_path(tab: "categories")
  end
end

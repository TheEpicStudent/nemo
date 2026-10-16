module Fd
  module ManagesNotes
    private

    def note_body_error(body, field)
      return field_error!(field, "Enter the note") if body.blank?

      max_length = NotesController::MAX_LENGTH
      return field_error!(field, "Keep it under #{max_length} characters", body) if body.length > max_length

      nil
    end

    def edit_note(note, body)
      return false if body == note.body

      writing do
        note.edit!(body, by: current_account.user_id)
        audit(note, "edited")
      end
      true
    end

    def remove_note(note)
      now = Time.current
      removed = false
      writing do
        rows = Note.where(id: note.id, deleted_at: nil)
          .update_all(deleted_at: now, deleted_by: current_account.user_id, updated_at: now)
        next if rows.zero?

        removed = true
        note.reload
        audit(note, "deleted",
          before: { "deleted_at" => nil },
          after: { "deleted_at" => note.deleted_at, "deleted_by" => note.deleted_by, "body" => note.body })
      end
      removed
    end
  end
end

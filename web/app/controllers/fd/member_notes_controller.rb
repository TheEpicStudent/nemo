module Fd
  class MemberNotesController < BaseController
    include ManagesNotes

    permit "member.note"

    def create
      user_id = params[:member_id].to_s.upcase
      body = Mentions.normalise(params[:body].to_s.strip)

      error = validation_error(body)
      if error
        return redirect_to(fd_member_path(user_id),
          alert: (error unless flash[:field_error]))
      end

      writing do
        note = Note.create!(subject_user_id: user_id, body: body, author: current_account.user_id)
        audit(note, "noted")
      end

      flash[:action] = { "label" => "See their record", "href" => fd_member_path(user_id) }
      redirect_to fd_member_path(user_id),
        notice: "Noted; it now follows them to every case"
    end

    def update
      user_id = params[:member_id].to_s.upcase
      note = Note.for_subject(user_id).visible.find_by(id: params[:id])
      return redirect_to(fd_member_path(user_id), alert: "Note not found") if note.nil?

      body = Mentions.normalise(params[:body].to_s.strip)
      error = note_body_error(body, :edit_body)
      if error
        return redirect_to(fd_member_path(user_id, do: "edit-note-#{note.id}"),
          alert: (error unless flash[:field_error]))
      end

      redirect_to fd_member_path(user_id), notice: edit_note(note, body) ? "Note updated" : "No changes"
    end

    def destroy
      user_id = params[:member_id].to_s.upcase
      note = Note.for_subject(user_id).visible.find_by(id: params[:id])

      if note && remove_note(note)
        redirect_to fd_member_path(user_id), notice: "Note removed"
      else
        redirect_to fd_member_path(user_id), alert: "Note not found"
      end
    end

    private

    def validation_error(body)
      return wrong!(:body, "Write the note before saving it.") if body.blank?

      max_length = NotesController::MAX_LENGTH
      if body.length > max_length
        return wrong!(:body, "Keep it under #{max_length} characters. That one is #{body.length}.", body)
      end

      nil
    end
  end
end

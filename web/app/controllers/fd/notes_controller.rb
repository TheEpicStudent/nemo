module Fd
  class NotesController < BaseController
    include ManagesNotes

    MAX_LENGTH = 5_000

    permit "case.note"

    def create
      kase = Case.find(params[:case_id])
      body = Mentions.normalise(params[:body].to_s.strip)
      about = params[:about].to_s
      standing = about.present? && about != "case"

      error = validation_error(kase, body, standing, about)
      if error
        return redirect_to(back_to(kase, standing, about),
          alert: (error unless flash[:field_error]))
      end

      writing do
        note = Note.create!(
          case_id: standing ? nil : kase.id,
          subject_user_id: standing ? about : nil,
          body: body,
          author: current_account.user_id
        )
        audit(note, "noted")
      end

      redirect_to back_to(kase, standing, about), notice: notice_for(kase, standing, about)
    end

    def update
      kase = Case.find(params[:case_id])
      note = on_this_page(kase).visible.find_by(id: params[:id])
      return redirect_to(fd_case_path(kase, tab: "notes"), alert: "Note not found") if note.nil?

      about = note.subject_user_id
      body = Mentions.normalise(params[:body].to_s.strip)
      error = note_body_error(body, :edit_body)
      if error
        return redirect_to(back_to(kase, about.present?, about, do: "edit-note-#{note.id}"),
          alert: (error unless flash[:field_error]))
      end

      notice = edit_note(note, body) ? "Note updated" : "No changes"
      redirect_to back_to(kase, about.present?, about), notice: notice
    end

    def destroy
      kase = Case.find(params[:case_id])
      note = on_this_page(kase).visible.find_by(id: params[:id])
      about = note&.subject_user_id

      if note && remove_note(note)
        redirect_to back_to(kase, about.present?, about), notice: "Note removed"
      else
        redirect_to back_to(kase, about.present?, about), alert: "Note not found"
      end
    end

    private

    def back_to(kase, standing, about, **extra)
      return fd_case_path(kase, tab: "people", person: about, **extra) if standing
      return fd_case_path(kase, tab: "report", **extra) if params[:from] == "report"

      fd_case_path(kase, tab: "notes", **extra)
    end

    def on_this_page(kase)
      Note.where(case_id: kase.family_ids)
        .or(Note.standing.where(subject_user_id: kase.subject_user_ids))
    end

    def validation_error(kase, body, standing, about)
      return wrong!(:body, "Write the note before saving it.") if body.blank?
      if body.length > MAX_LENGTH
        return wrong!(:body,
          "Keep it under #{MAX_LENGTH} characters. That one is #{body.length}.", body)
      end
      if standing && !kase.subject_user_ids.include?(about)
        return "that member is not a subject of this case"
      end

      nil
    end

    def notice_for(kase, standing, about)
      standing ? "noted against @#{about}" : "note added to case #{kase.id}"
    end
  end
end

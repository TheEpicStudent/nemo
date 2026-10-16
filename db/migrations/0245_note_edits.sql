ALTER TABLE fd.notes
    ADD COLUMN edited_at timestamptz,
    ADD COLUMN edited_by text,
    ADD CONSTRAINT notes_edited_together CHECK ((edited_at IS NULL) = (edited_by IS NULL));

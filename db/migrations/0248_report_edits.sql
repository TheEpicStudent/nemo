ALTER TABLE fd.intake_messages ADD COLUMN shown_body text;

ALTER TABLE fd.intake_outbox DROP CONSTRAINT intake_outbox_kind_check;
ALTER TABLE fd.intake_outbox
    ADD CONSTRAINT intake_outbox_kind_check CHECK (kind IN ('reply', 'outcome', 'edit'));

ALTER TABLE fd.intake_outbox ADD COLUMN edits_outbox_id bigint REFERENCES fd.intake_outbox(id);
ALTER TABLE fd.intake_outbox
    ADD CONSTRAINT intake_outbox_edit_has_target CHECK ((kind = 'edit') = (edits_outbox_id IS NOT NULL));

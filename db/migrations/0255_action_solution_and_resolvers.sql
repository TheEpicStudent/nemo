ALTER TABLE fd.actions
    ADD COLUMN solution text,
    ADD COLUMN resolved_by text[] NOT NULL DEFAULT '{}';

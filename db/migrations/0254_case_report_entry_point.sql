ALTER TABLE fd.case_reports
    ADD COLUMN entry_point text NOT NULL DEFAULT 'dm'
    CONSTRAINT case_reports_entry_point_known CHECK (entry_point IN ('dm', 'shortcut'));

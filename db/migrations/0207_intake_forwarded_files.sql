ALTER TABLE fd.intake_message_files
    ADD COLUMN IF NOT EXISTS forwarded boolean NOT NULL DEFAULT false;

UPDATE fd.intake_message_files mf
SET forwarded = true
FROM fd.intake_files f, fd.intake_shares s
WHERE f.id = mf.file_id
  AND s.message_id = mf.message_id
  AND s.kind = 'forward'
  AND s.raw -> 'files' @> jsonb_build_array(jsonb_build_object('id', f.slack_file_id))
  AND NOT mf.forwarded;

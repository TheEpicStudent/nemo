ALTER TABLE fd.intake_messages
    ADD COLUMN IF NOT EXISTS unfurl_ts text,
    ADD COLUMN IF NOT EXISTS unfurl_digest text,
    ADD COLUMN IF NOT EXISTS unfurled_at timestamptz;

UPDATE fd.intake_messages
SET unfurled_at = coalesce(mirrored_at, now())
WHERE mirrored_ts IS NOT NULL AND unfurled_at IS NULL;

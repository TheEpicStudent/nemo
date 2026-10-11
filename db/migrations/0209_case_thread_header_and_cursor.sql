ALTER TABLE fd.case_reports ADD COLUMN IF NOT EXISTS header_ts text;

ALTER TABLE fd.cases ADD COLUMN IF NOT EXISTS card_header_ts text;

ALTER TABLE fd.case_chat ADD COLUMN IF NOT EXISTS unfurl_ts text;

CREATE TABLE IF NOT EXISTS fd.bot_cursor (
    name text PRIMARY KEY,
    last_id bigint NOT NULL
);

INSERT INTO fd.bot_cursor (name, last_id)
SELECT 'fire_engine_audit', coalesce(max(id), 0) FROM fd.audit
ON CONFLICT (name) DO NOTHING;

ALTER TABLE raw.worker_heartbeat
    ADD COLUMN IF NOT EXISTS build text;

CREATE TABLE IF NOT EXISTS raw.worker_build (
    build text PRIMARY KEY,
    first_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ingest_run_source_started_idx
    ON raw.ingest_run (source, started_at DESC);

CREATE OR REPLACE VIEW fd.link_lane_run AS
SELECT s.source, r.started_at, r.finished_at, r.status, r.rows_in
FROM unnest(ARRAY['member_links', 'member_links_live', 'member_clusters']) AS s(source)
LEFT JOIN LATERAL (
    SELECT i.started_at, i.finished_at, i.status, i.rows_in
    FROM raw.ingest_run i
    WHERE i.source = s.source
    ORDER BY i.started_at DESC
    LIMIT 1
) r ON true;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
        GRANT SELECT ON fd.link_lane_run TO pipeline_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rails_app') THEN
        GRANT SELECT ON fd.link_lane_run TO rails_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dbt_owner') THEN
        REVOKE ALL ON fd.link_lane_run FROM dbt_owner;
    END IF;
END
$$;

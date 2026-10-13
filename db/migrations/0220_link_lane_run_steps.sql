CREATE OR REPLACE VIEW fd.link_lane_run AS
SELECT s.source, r.started_at, r.finished_at, r.status, r.rows_in, r.steps
FROM unnest(ARRAY['member_links', 'member_links_live', 'member_clusters']) AS s(source)
LEFT JOIN LATERAL (
    SELECT i.started_at, i.finished_at, i.status, i.rows_in,
           (SELECT jsonb_agg(jsonb_build_object(
                       'name', split_part(c.source, ':', 2),
                       'seconds', round(extract(epoch FROM c.finished_at - c.started_at)::numeric, 2))
                   ORDER BY c.step_index)
            FROM raw.ingest_run c
            WHERE c.parent_run_id = i.id AND c.finished_at IS NOT NULL) AS steps
    FROM raw.ingest_run i
    WHERE i.source = s.source
    ORDER BY i.started_at DESC
    LIMIT 1
) r ON true;

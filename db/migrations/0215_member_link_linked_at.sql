ALTER TABLE fd.member_link ADD COLUMN IF NOT EXISTS linked_at timestamptz;
ALTER TABLE fd.member_link ALTER COLUMN linked_at SET DEFAULT clock_timestamp();

CREATE INDEX IF NOT EXISTS member_link_linked_at_idx ON fd.member_link (linked_at)
    WHERE linked_at IS NOT NULL;

CREATE OR REPLACE VIEW fd.link_latency AS
SELECT l.a_user_id, l.b_user_id, l.score, l.top_signal, l.linked_at,
       greatest(ja.joined_at, jb.joined_at) AS later_join,
       sign_in.at AS last_sign_in,
       extract(epoch FROM l.linked_at - greatest(ja.joined_at, jb.joined_at)) AS from_join_seconds,
       extract(epoch FROM l.linked_at - sign_in.at) AS from_sign_in_seconds
FROM fd.member_link l
LEFT JOIN fd.member_joins ja ON ja.user_id = l.a_user_id
LEFT JOIN fd.member_joins jb ON jb.user_id = l.b_user_id
LEFT JOIN LATERAL (
    SELECT max(CASE WHEN e.last_at <= l.linked_at THEN e.last_at ELSE e.first_at END) AS at
    FROM fd.login_event e
    WHERE e.user_id IN (l.a_user_id, l.b_user_id) AND e.first_at <= l.linked_at
) sign_in ON true
WHERE l.linked_at >= now() - interval '7 days';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
        GRANT SELECT ON fd.link_latency TO pipeline_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rails_app') THEN
        GRANT SELECT ON fd.link_latency TO rails_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dbt_owner') THEN
        REVOKE ALL ON fd.link_latency FROM dbt_owner;
    END IF;
END
$$;

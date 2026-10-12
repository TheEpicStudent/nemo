CREATE OR REPLACE VIEW fd.member_account AS
SELECT d.user_id,
       coalesce(d.invite_pending, false) AS invite_pending,
       d.claimed_at,
       coalesce(d.is_deleted, false) OR d.deactivated_at IS NOT NULL AS deactivated,
       s.last_login_at,
       s.last_post_at
FROM raw.member_dim d
LEFT JOIN fd.member_seen s ON s.user_id = d.user_id;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
        GRANT SELECT ON fd.member_account TO pipeline_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rails_app') THEN
        GRANT SELECT ON fd.member_account TO rails_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dbt_owner') THEN
        REVOKE ALL ON fd.member_account FROM dbt_owner;
    END IF;
END
$$;

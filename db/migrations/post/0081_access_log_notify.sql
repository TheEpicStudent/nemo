CREATE OR REPLACE FUNCTION fd.access_log_inserted()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM inserted) THEN
        RETURN NULL;
    END IF;
    PERFORM pg_notify('fd_audit_event', jsonb_build_object(
        'source', 'read',
        'truncated', (SELECT count(*) > 50 FROM inserted),
        'actions', '["read"]'::jsonb,
        'actors', (SELECT coalesce(jsonb_agg(actor_id), '[]') FROM (
            SELECT DISTINCT actor_id FROM inserted WHERE actor_id IS NOT NULL LIMIT 50) actors),
        'subjects', (SELECT coalesce(jsonb_agg(subject_user_id), '[]') FROM (
            SELECT DISTINCT subject_user_id FROM inserted WHERE subject_user_id IS NOT NULL LIMIT 50) subjects)
    )::text);
    RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS access_log_inserted ON app.access_log;
CREATE TRIGGER access_log_inserted
    AFTER INSERT ON app.access_log
    REFERENCING NEW TABLE AS inserted
    FOR EACH STATEMENT EXECUTE FUNCTION fd.access_log_inserted();

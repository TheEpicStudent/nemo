CREATE OR REPLACE FUNCTION fd.slack_audit_event_inserted()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM inserted) THEN
        RETURN NULL;
    END IF;
    PERFORM pg_notify('fd_audit_event', jsonb_build_object(
        'source', 'slack',
        'truncated', (SELECT count(*) > 50 FROM inserted),
        'actions', (SELECT coalesce(jsonb_agg(action), '[]') FROM (
            SELECT DISTINCT action FROM inserted WHERE action IS NOT NULL LIMIT 50) actions),
        'actors', (SELECT coalesce(jsonb_agg(actor_id), '[]') FROM (
            SELECT DISTINCT actor_id FROM inserted WHERE actor_id IS NOT NULL LIMIT 50) actors),
        'subjects', (SELECT coalesce(jsonb_agg(entity_id), '[]') FROM (
            SELECT DISTINCT entity_id FROM inserted WHERE entity_id IS NOT NULL LIMIT 50) subjects)
    )::text);
    RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS slack_audit_event_inserted ON slack.audit_event;
CREATE TRIGGER slack_audit_event_inserted
    AFTER INSERT ON slack.audit_event
    REFERENCING NEW TABLE AS inserted
    FOR EACH STATEMENT EXECUTE FUNCTION fd.slack_audit_event_inserted();

CREATE OR REPLACE FUNCTION fd.fd_audit_inserted()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM inserted) THEN
        RETURN NULL;
    END IF;
    PERFORM pg_notify('fd_audit_event', jsonb_build_object(
        'source', 'fire_engine',
        'truncated', (SELECT count(*) > 50 FROM inserted),
        'actions', (SELECT coalesce(jsonb_agg(verb), '[]') FROM (
            SELECT DISTINCT verb FROM inserted WHERE verb IS NOT NULL LIMIT 50) actions),
        'actors', (SELECT coalesce(jsonb_agg(actor_user_id), '[]') FROM (
            SELECT DISTINCT actor_user_id FROM inserted WHERE actor_user_id IS NOT NULL LIMIT 50) actors),
        'subjects', (SELECT coalesce(jsonb_agg(subject_user_id), '[]') FROM (
            SELECT DISTINCT subject_user_id FROM inserted WHERE subject_user_id IS NOT NULL LIMIT 50) subjects)
    )::text);
    RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS fd_audit_inserted ON fd.audit;
CREATE TRIGGER fd_audit_inserted
    AFTER INSERT ON fd.audit
    REFERENCING NEW TABLE AS inserted
    FOR EACH STATEMENT EXECUTE FUNCTION fd.fd_audit_inserted();

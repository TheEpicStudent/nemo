ALTER TABLE fd.member_trait DROP CONSTRAINT member_trait_kind_known;
ALTER TABLE fd.member_trait ADD CONSTRAINT member_trait_kind_known CHECK (kind IN (
    'ip', 'ip_prefix', 'ua_id', 'ja4', 'ja3',
    'email_domain', 'mailbox', 'local_part',
    'full_name', 'display_name', 'handle_stem', 'inviter'
));

CREATE OR REPLACE FUNCTION fd.audit_event_traits()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    owner_id text;
BEGIN
    IF NEW.action = 'anomaly' THEN
        owner_id := NEW.actor_id;
    ELSIF NEW.entity_id IS DISTINCT FROM NEW.actor_id THEN
        owner_id := NEW.entity_id;
    END IF;
    IF owner_id IS NULL THEN
        RETURN NULL;
    END IF;
    INSERT INTO fd.member_trait AS held (user_id, kind, value, first_seen, last_seen, seen)
    SELECT owner_id, one.kind, one.value, NEW.at, NEW.at, 1
    FROM (VALUES
        ('ja4', CASE WHEN NEW.action = 'anomaly' THEN NEW.payload->'details'->>'client_ja4_fingerprint' END),
        ('ja3', CASE WHEN NEW.action = 'anomaly' THEN NEW.payload->'details'->>'client_ja3_fingerprint' END),
        ('inviter', CASE WHEN NEW.action <> 'anomaly' THEN NEW.actor_id END)
    ) AS one (kind, value)
    WHERE one.value IS NOT NULL
    ON CONFLICT (user_id, kind, value) DO UPDATE SET
        first_seen = least(held.first_seen, EXCLUDED.first_seen),
        last_seen = greatest(held.last_seen, EXCLUDED.last_seen),
        seen = held.seen + 1,
        updated_at = now();
    RETURN NULL;
END
$$;

ALTER TABLE fd.member_trait DISABLE TRIGGER member_trait_touches;

INSERT INTO fd.member_trait (user_id, kind, value, first_seen, last_seen, seen)
SELECT actor_id, 'ja3', payload->'details'->>'client_ja3_fingerprint', min(at), max(at), count(*)
FROM slack.audit_event
WHERE action = 'anomaly' AND actor_id IS NOT NULL
  AND payload->'details'->>'client_ja3_fingerprint' IS NOT NULL
GROUP BY 1, 3
ON CONFLICT (user_id, kind, value) DO NOTHING;

ALTER TABLE fd.member_trait ENABLE TRIGGER member_trait_touches;

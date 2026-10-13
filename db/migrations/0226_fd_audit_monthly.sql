CREATE TABLE fd.audit_monthly (
    id              bigint      GENERATED ALWAYS AS IDENTITY,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    actor_user_id   text,
    actor_kind      text        NOT NULL,
    entity_type     text        NOT NULL,
    entity_id       bigint      NOT NULL,
    verb            text        NOT NULL,
    before          jsonb,
    after           jsonb,
    source_app      text        NOT NULL,
    request_id      text,
    entity_ref      text,
    subject_user_id text,
    searchable      tsvector GENERATED ALWAYS AS (
        to_tsvector('simple'::regconfig,
            coalesce(verb, '') || ' ' ||
            coalesce(entity_type, '') || ' ' ||
            coalesce(actor_user_id, '') || ' ' ||
            coalesce(entity_ref, '') || ' ' ||
            coalesce(subject_user_id, '') || ' ' ||
            coalesce(entity_id::text, ''))
        ||
        jsonb_to_tsvector('simple'::regconfig, coalesce(before, '{}'::jsonb), '["string"]')
        ||
        jsonb_to_tsvector('simple'::regconfig, coalesce(after, '{}'::jsonb), '["string"]')
    ) STORED,
    PRIMARY KEY (id, occurred_at),
    CONSTRAINT audit_actor_kind_check CHECK (actor_kind IN ('human', 'bot', 'system', 'import'))
) PARTITION BY RANGE (occurred_at);

CREATE INDEX audit_monthly_entity_idx ON fd.audit_monthly (entity_type, entity_id, occurred_at DESC);
CREATE INDEX audit_monthly_actor_idx ON fd.audit_monthly (actor_user_id, occurred_at DESC)
    WHERE actor_user_id IS NOT NULL;
CREATE INDEX audit_monthly_entity_ref_idx ON fd.audit_monthly (entity_type, entity_ref)
    WHERE entity_ref IS NOT NULL;
CREATE INDEX audit_monthly_recent_idx ON fd.audit_monthly (occurred_at DESC, id DESC);
CREATE INDEX audit_monthly_subject_idx ON fd.audit_monthly (subject_user_id, occurred_at DESC)
    WHERE subject_user_id IS NOT NULL;
CREATE INDEX audit_monthly_verb_idx ON fd.audit_monthly (verb, occurred_at DESC);
CREATE INDEX audit_monthly_search_idx ON fd.audit_monthly USING gin (searchable);

CREATE TABLE fd.audit_default PARTITION OF fd.audit_monthly DEFAULT;
CREATE TABLE fd.audit_2026_09 PARTITION OF fd.audit_monthly
    FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');
CREATE TABLE fd.audit_2026_10 PARTITION OF fd.audit_monthly
    FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');
CREATE TABLE fd.audit_2026_11 PARTITION OF fd.audit_monthly
    FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');
CREATE TABLE fd.audit_2026_12 PARTITION OF fd.audit_monthly
    FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');

INSERT INTO fd.audit_monthly
    (id, occurred_at, actor_user_id, actor_kind, entity_type, entity_id, verb, before, after,
     source_app, request_id, entity_ref, subject_user_id)
OVERRIDING SYSTEM VALUE
SELECT id, occurred_at, actor_user_id, actor_kind, entity_type, entity_id, verb, before, after,
       source_app, request_id, entity_ref, subject_user_id
FROM fd.audit;

SELECT setval(pg_get_serial_sequence('fd.audit_monthly', 'id'),
              coalesce((SELECT max(id) FROM fd.audit_monthly), 1));

DROP TABLE fd.audit;

ALTER TABLE fd.audit_monthly RENAME TO audit;
ALTER TABLE fd.audit RENAME CONSTRAINT audit_monthly_pkey TO audit_pkey;
ALTER INDEX fd.audit_monthly_entity_idx RENAME TO audit_entity_idx;
ALTER INDEX fd.audit_monthly_actor_idx RENAME TO audit_actor_idx;
ALTER INDEX fd.audit_monthly_entity_ref_idx RENAME TO audit_entity_ref_idx;
ALTER INDEX fd.audit_monthly_recent_idx RENAME TO audit_recent_idx;
ALTER INDEX fd.audit_monthly_subject_idx RENAME TO audit_subject_idx;
ALTER INDEX fd.audit_monthly_verb_idx RENAME TO audit_verb_idx;
ALTER INDEX fd.audit_monthly_search_idx RENAME TO audit_search_idx;

CREATE TRIGGER fd_audit_inserted
    AFTER INSERT ON fd.audit
    REFERENCING NEW TABLE AS inserted
    FOR EACH STATEMENT EXECUTE FUNCTION fd.fd_audit_inserted();

DO $$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['rails_app', 'pipeline_writer'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE UPDATE, DELETE ON fd.audit FROM %I', role_name);
        END IF;
    END LOOP;
END
$$;

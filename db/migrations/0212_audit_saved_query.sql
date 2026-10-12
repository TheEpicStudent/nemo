CREATE TABLE IF NOT EXISTS fd.audit_saved_query (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          text        NOT NULL,
    query         text        NOT NULL,
    view          text,
    owner_user_id text,
    created_by    text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_saved_query_name_length CHECK (char_length(name) BETWEEN 1 AND 80),
    CONSTRAINT audit_saved_query_query_length CHECK (char_length(query) BETWEEN 1 AND 500)
);

CREATE INDEX IF NOT EXISTS audit_saved_query_owner_idx ON fd.audit_saved_query (owner_user_id);

INSERT INTO fd.audit_saved_query (name, query, view, created_by)
SELECT defaults.name, defaults.query, defaults.view, 'system'
FROM (VALUES
    ('Sign-ins', 'category:sign_ins', NULL),
    ('Sign-ins from Tor', 'category:sign_ins network:tor', NULL),
    ('Admin role changes', 'category:admin_and_roles', NULL),
    ('Deactivations', 'did:user_deactivated did:deactivated', 'everything'),
    ('My actions', 'by:me', 'everything')
) AS defaults(name, query, view)
WHERE NOT EXISTS (SELECT 1 FROM fd.audit_saved_query);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rails_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON fd.audit_saved_query TO rails_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
        GRANT SELECT ON fd.audit_saved_query TO pipeline_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dbt_owner') THEN
        REVOKE ALL ON fd.audit_saved_query FROM dbt_owner;
    END IF;
END
$$;

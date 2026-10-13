CREATE TABLE IF NOT EXISTS fd.throwaway_domain (
    domain       text        PRIMARY KEY,
    source       text        NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT throwaway_domain_source_known CHECK (source IN ('list', 'curated')),
    CONSTRAINT throwaway_domain_lowercase CHECK (domain = lower(domain))
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON fd.throwaway_domain TO pipeline_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rails_app') THEN
        GRANT SELECT ON fd.throwaway_domain TO rails_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dbt_owner') THEN
        REVOKE ALL ON fd.throwaway_domain FROM dbt_owner;
    END IF;
END
$$;

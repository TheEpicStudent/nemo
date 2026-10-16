CREATE TABLE fd.log_cursors (
    name text PRIMARY KEY,
    last_id bigint NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO fd.log_cursors (name, last_id)
VALUES ('audit', coalesce((SELECT max(id) FROM fd.audit), 0)),
       ('automod', coalesce((SELECT max(id) FROM fd.automod_matches), 0));

CREATE OR REPLACE FUNCTION fd.automod_match_inserted() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('fd_automod_match', '');
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER automod_matches_inserted
    AFTER INSERT ON fd.automod_matches
    FOR EACH STATEMENT EXECUTE FUNCTION fd.automod_match_inserted();

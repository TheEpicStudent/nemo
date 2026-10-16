CREATE TABLE fd.bot_kicks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guard_id bigint NOT NULL REFERENCES fd.channel_guards(id) ON DELETE CASCADE,
    channel_id text NOT NULL,
    subject_id text NOT NULL,
    queued_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0,
    done_at timestamptz,
    outcome text
);

CREATE INDEX bot_kicks_waiting ON fd.bot_kicks (queued_at) WHERE done_at IS NULL;

CREATE OR REPLACE FUNCTION fd.channel_guard_allow_removed() RETURNS trigger AS $$
BEGIN
    INSERT INTO fd.bot_kicks (guard_id, channel_id, subject_id)
    SELECT g.id, g.channel_id, OLD.subject_id
    FROM fd.channel_guards g
    WHERE g.id = OLD.guard_id AND g.kind = 'bot_allowlist' AND g.state = 'live';

    IF FOUND THEN
        PERFORM pg_notify('fd_bot_kick', OLD.subject_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER channel_guard_allows_removed
    AFTER DELETE ON fd.channel_guard_allows
    FOR EACH ROW EXECUTE FUNCTION fd.channel_guard_allow_removed();

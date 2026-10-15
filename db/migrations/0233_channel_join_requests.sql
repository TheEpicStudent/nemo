CREATE TABLE fd.channel_join_requests (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel_id text NOT NULL,
    requested_by text NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    state text NOT NULL DEFAULT 'queued',
    error text,
    finished_at timestamptz,
    CONSTRAINT channel_join_requests_state_known CHECK (state IN ('queued', 'joined', 'refused')),
    CONSTRAINT channel_join_requests_finished_together
        CHECK ((state = 'queued') = (finished_at IS NULL))
);

CREATE UNIQUE INDEX channel_join_requests_one_queued
    ON fd.channel_join_requests (channel_id) WHERE state = 'queued';

CREATE INDEX channel_join_requests_recent ON fd.channel_join_requests (requested_at DESC);

CREATE FUNCTION fd.channel_join_requested() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('fd_channel_join_request', NEW.id::text);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER channel_join_requests_notify
    AFTER INSERT ON fd.channel_join_requests
    FOR EACH ROW EXECUTE FUNCTION fd.channel_join_requested();

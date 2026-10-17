ALTER TABLE fd.channel_guards
    ADD COLUMN notice_stale boolean NOT NULL DEFAULT false,
    ADD COLUMN notice_removed_at timestamptz;

CREATE INDEX channel_guards_notice_stale
    ON fd.channel_guards (id)
    WHERE notice_stale;

CREATE INDEX channel_guards_notice_unremoved
    ON fd.channel_guards (id)
    WHERE state = 'lifted' AND notice_ts IS NOT NULL AND notice_removed_at IS NULL;

CREATE OR REPLACE FUNCTION fd.channel_guard_notice_changed() RETURNS trigger AS $$
BEGIN
    IF NEW.kind = 'slowmode' AND NEW.notice_ts IS NOT NULL THEN
        IF NEW.state = 'live'
           AND (NEW.settings IS DISTINCT FROM OLD.settings OR NEW.expires_at IS DISTINCT FROM OLD.expires_at) THEN
            NEW.notice_stale := true;
            PERFORM pg_notify('fd_guard_notice', NEW.id::text);
        ELSIF NEW.state = 'lifted' AND OLD.state = 'live' THEN
            PERFORM pg_notify('fd_guard_notice', NEW.id::text);
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER channel_guards_notice_changed
    BEFORE UPDATE ON fd.channel_guards
    FOR EACH ROW EXECUTE FUNCTION fd.channel_guard_notice_changed();

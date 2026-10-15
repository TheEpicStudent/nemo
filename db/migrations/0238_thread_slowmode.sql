ALTER TABLE fd.channel_guards
    ADD COLUMN thread_ts text NOT NULL DEFAULT '',
    ADD COLUMN expires_at timestamptz,
    ADD COLUMN reason text;

ALTER TABLE fd.channel_guards
    ADD CONSTRAINT channel_guards_thread_slowmode_only
    CHECK (thread_ts = '' OR kind = 'slowmode');

DROP INDEX fd.channel_guards_one_live;

CREATE UNIQUE INDEX channel_guards_one_live
    ON fd.channel_guards (channel_id, kind, thread_ts)
    WHERE state = 'live';

CREATE INDEX channel_guards_expiring
    ON fd.channel_guards (expires_at)
    WHERE state = 'live' AND expires_at IS NOT NULL;

DROP TRIGGER channel_guards_changed ON fd.channel_guards;

CREATE TRIGGER channel_guards_changed
    AFTER INSERT OR UPDATE OF state, settings, expires_at OR DELETE ON fd.channel_guards
    FOR EACH ROW EXECUTE FUNCTION fd.channel_guard_changed();

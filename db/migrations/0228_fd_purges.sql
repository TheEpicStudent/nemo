ALTER TABLE fd.channel_purges RENAME TO purges;
ALTER SEQUENCE fd.channel_purges_id_seq RENAME TO purges_id_seq;
ALTER INDEX fd.channel_purges_pkey RENAME TO purges_pkey;
ALTER INDEX fd.channel_purges_waiting RENAME TO purges_waiting;
ALTER INDEX fd.channel_purges_recent RENAME TO purges_recent;
ALTER TABLE fd.purges RENAME CONSTRAINT channel_purges_case_id_fkey TO purges_case_id_fkey;
ALTER TABLE fd.purges RENAME CONSTRAINT channel_purges_finished_together TO purges_finished_together;

ALTER TABLE fd.purges
    DROP CONSTRAINT channel_purges_state_known,
    DROP CONSTRAINT channel_purges_wanted_sane,
    DROP CONSTRAINT channel_purges_reason_present,
    ALTER COLUMN channel_id DROP NOT NULL,
    ALTER COLUMN wanted DROP NOT NULL,
    ALTER COLUMN reason DROP NOT NULL,
    ADD COLUMN member_id text,
    ADD COLUMN source text NOT NULL DEFAULT 'web',
    ADD COLUMN guard_id bigint REFERENCES fd.member_guards(id),
    ADD COLUMN found integer,
    ADD COLUMN left_after_check integer,
    ADD COLUMN checked_at timestamptz,
    ADD CONSTRAINT purges_state_known
        CHECK (state IN ('proposed', 'asked', 'running', 'checking', 'done', 'failed')),
    ADD CONSTRAINT purges_wanted_sane CHECK (wanted IS NULL OR wanted BETWEEN 1 AND 10000),
    ADD CONSTRAINT purges_reason_present CHECK (reason IS NULL OR btrim(reason) <> ''),
    ADD CONSTRAINT purges_source_known CHECK (source IN ('web', 'slack', 'deactivation')),
    ADD CONSTRAINT purges_names_a_target CHECK (channel_id IS NOT NULL OR member_id IS NOT NULL);

DROP INDEX fd.channel_purges_one_running;

CREATE UNIQUE INDEX purges_one_waiting
    ON fd.purges (coalesce(channel_id, ''), coalesce(member_id, ''))
    WHERE state IN ('asked', 'running', 'checking');

CREATE INDEX purges_member_recent ON fd.purges (member_id, asked_at DESC)
    WHERE member_id IS NOT NULL;

DROP TRIGGER channel_purges_asked ON fd.purges;
DROP FUNCTION fd.channel_purge_asked();

CREATE FUNCTION fd.purge_asked() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('fd_purge', NEW.id::text);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER purges_asked
    AFTER INSERT OR UPDATE OF state ON fd.purges
    FOR EACH ROW WHEN (NEW.state = 'asked')
    EXECUTE FUNCTION fd.purge_asked();

CREATE TABLE fd.purge_items (
    purge_id bigint NOT NULL REFERENCES fd.purges(id) ON DELETE CASCADE,
    channel_id text NOT NULL,
    ts text NOT NULL,
    thread_ts text,
    author_id text,
    text text,
    state text NOT NULL DEFAULT 'queued',
    error text,
    found_at timestamptz NOT NULL DEFAULT now(),
    done_at timestamptz,
    PRIMARY KEY (purge_id, channel_id, ts),
    CONSTRAINT purge_items_state_known CHECK (state IN ('queued', 'deleted', 'gone', 'failed')),
    CONSTRAINT purge_items_done_together CHECK ((state = 'queued') = (done_at IS NULL))
);

CREATE INDEX purge_items_queued ON fd.purge_items (purge_id) WHERE state = 'queued';

INSERT INTO fd.purge_items (purge_id, channel_id, ts, thread_ts, author_id, text, state, found_at, done_at)
SELECT p.id, p.channel_id, entry ->> 'ts', nullif(entry ->> 'thread_ts', ''), entry ->> 'user',
       entry ->> 'text', 'deleted', p.asked_at, coalesce(p.finished_at, p.asked_at)
FROM fd.purges p
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(p.transcript) = 'array' THEN p.transcript ELSE '[]'::jsonb END
) AS entry
WHERE entry ->> 'ts' IS NOT NULL
ON CONFLICT (purge_id, channel_id, ts) DO NOTHING;

ALTER TABLE fd.purges DROP COLUMN transcript;

CREATE TABLE fd.import_map (
    source_app text NOT NULL,
    source_table text NOT NULL,
    source_key text NOT NULL,
    entity_table text NOT NULL,
    entity_id bigint NOT NULL,
    source_digest text,
    synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_app, source_table, source_key)
);

CREATE INDEX import_map_entity_idx ON fd.import_map (entity_table, entity_id);

CREATE TABLE fd.lyla_outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity text NOT NULL,
    entity_id bigint NOT NULL,
    case_id bigint,
    op text NOT NULL,
    before jsonb,
    after jsonb,
    queued_at timestamptz NOT NULL DEFAULT now(),
    applied_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    error text,
    conflict text,
    CONSTRAINT lyla_outbox_op_known CHECK (op IN ('insert', 'update', 'delete'))
);

CREATE INDEX lyla_outbox_waiting_idx ON fd.lyla_outbox (id) WHERE applied_at IS NULL;
CREATE INDEX lyla_outbox_case_idx ON fd.lyla_outbox (case_id) WHERE applied_at IS NULL;

CREATE TABLE fd.lyla_case_numbers (
    number bigint PRIMARY KEY,
    reserved_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE fd.lyla_sync_status (
    name text PRIMARY KEY,
    ran_at timestamptz,
    ok_at timestamptz,
    error text
);

CREATE FUNCTION fd.take_lyla_case_number() RETURNS trigger AS $$
DECLARE
    taken bigint;
BEGIN
    DELETE FROM fd.lyla_case_numbers
    WHERE number = (
        SELECT number FROM fd.lyla_case_numbers
        ORDER BY number
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING number INTO taken;

    IF taken IS NOT NULL THEN
        NEW.id := taken;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cases_take_lyla_number
    BEFORE INSERT ON fd.cases
    FOR EACH ROW
    WHEN (current_setting('fd.sync_source', true) IS DISTINCT FROM 'lyla')
    EXECUTE FUNCTION fd.take_lyla_case_number();

CREATE FUNCTION fd.queue_lyla_change() RETURNS trigger AS $$
DECLARE
    old_row jsonb;
    new_row jsonb;
    current_row jsonb;
    watched text;
    changed boolean;
    queued bigint;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        old_row := to_jsonb(OLD);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        new_row := to_jsonb(NEW);
    END IF;

    changed := TG_OP <> 'UPDATE';
    IF NOT changed THEN
        FOREACH watched IN ARRAY TG_ARGV LOOP
            IF old_row -> watched IS DISTINCT FROM new_row -> watched THEN
                changed := true;
                EXIT;
            END IF;
        END LOOP;
    END IF;

    IF NOT changed THEN
        RETURN NULL;
    END IF;

    current_row := coalesce(new_row, old_row);
    INSERT INTO fd.lyla_outbox (entity, entity_id, case_id, op, before, after)
    VALUES (
        TG_TABLE_NAME,
        coalesce((current_row ->> 'id')::bigint, (current_row ->> 'case_id')::bigint),
        CASE WHEN TG_TABLE_NAME = 'cases' THEN (current_row ->> 'id')::bigint
             ELSE (current_row ->> 'case_id')::bigint END,
        lower(TG_OP),
        old_row,
        new_row
    )
    RETURNING id INTO queued;

    PERFORM pg_notify('fd_lyla_outbox', queued::text);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cases_queue_lyla
    AFTER INSERT OR UPDATE OR DELETE ON fd.cases
    FOR EACH ROW
    WHEN (current_setting('fd.sync_source', true) IS DISTINCT FROM 'lyla')
    EXECUTE FUNCTION fd.queue_lyla_change(
        'resolved_at', 'resolution', 'duplicate_of', 'card_channel_id', 'card_thread_ts', 'card_ts');

CREATE TRIGGER case_reports_queue_lyla
    AFTER UPDATE ON fd.case_reports
    FOR EACH ROW
    WHEN (current_setting('fd.sync_source', true) IS DISTINCT FROM 'lyla')
    EXECUTE FUNCTION fd.queue_lyla_change('forwarded_ts', 'card_channel_id');

CREATE TRIGGER actions_queue_lyla
    AFTER INSERT OR UPDATE OR DELETE ON fd.actions
    FOR EACH ROW
    WHEN (current_setting('fd.sync_source', true) IS DISTINCT FROM 'lyla')
    EXECUTE FUNCTION fd.queue_lyla_change(
        'type_key', 'target_user_id', 'reason', 'solution', 'resolved_by', 'category_key',
        'expires_at', 'details', 'reversed_at');

CREATE TRIGGER case_assignees_queue_lyla
    AFTER INSERT OR DELETE ON fd.case_assignees
    FOR EACH ROW
    WHEN (current_setting('fd.sync_source', true) IS DISTINCT FROM 'lyla')
    EXECUTE FUNCTION fd.queue_lyla_change();

CREATE TRIGGER notes_queue_lyla
    AFTER INSERT OR UPDATE OR DELETE ON fd.notes
    FOR EACH ROW
    WHEN (current_setting('fd.sync_source', true) IS DISTINCT FROM 'lyla')
    EXECUTE FUNCTION fd.queue_lyla_change('body', 'deleted_at');

ALTER TABLE fd.notes ADD COLUMN external_ref text UNIQUE;

ALTER TABLE fd.cases ADD COLUMN chat_imported_at timestamptz;

ALTER TABLE fd.member_guards
    DROP CONSTRAINT member_guards_enforced_by_known,
    DROP CONSTRAINT member_guards_by_hand_is_held,
    ADD CONSTRAINT member_guards_enforced_by_known
        CHECK (enforced_by IN ('nemo', 'by_hand', 'firehose')),
    ADD CONSTRAINT member_guards_external_is_held
        CHECK (enforced_by = 'nemo' OR enforcement_status = 'held');

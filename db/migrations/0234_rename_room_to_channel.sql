ALTER INDEX IF EXISTS fd.member_channel_join_room_idx RENAME TO member_channel_join_channel_idx;

CREATE OR REPLACE FUNCTION fd.channel_guard_allow_changed() RETURNS trigger AS $$
DECLARE
    guarded_channel_id text;
BEGIN
    SELECT channel_id INTO guarded_channel_id FROM fd.channel_guards
    WHERE id = COALESCE(NEW.guard_id, OLD.guard_id);

    IF guarded_channel_id IS NOT NULL THEN
        PERFORM pg_notify('fd_channel_guard', guarded_channel_id);
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fd.member_touch_notify()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_notify('fd_member_touch', '*');
    RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS member_touch_notify ON fd.member_touch;
CREATE TRIGGER member_touch_notify
    AFTER INSERT OR UPDATE ON fd.member_touch
    FOR EACH STATEMENT EXECUTE FUNCTION fd.member_touch_notify();

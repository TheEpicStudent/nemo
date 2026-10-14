CREATE FUNCTION fd.purge_guard_settled() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('fd_purge', p.id::text)
    FROM fd.purges p
    WHERE p.guard_id = NEW.id AND p.state = 'asked';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER member_guards_wake_purges
    AFTER UPDATE OF enforcement_status, state ON fd.member_guards
    FOR EACH ROW
    WHEN ((NEW.enforcement_status = 'held' AND OLD.enforcement_status IS DISTINCT FROM 'held')
          OR (NEW.state = 'lifted' AND OLD.state IS DISTINCT FROM 'lifted'))
    EXECUTE FUNCTION fd.purge_guard_settled();

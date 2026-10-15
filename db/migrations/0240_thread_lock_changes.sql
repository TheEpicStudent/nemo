ALTER TABLE fd.thread_guards DROP CONSTRAINT thread_guards_lock_expires;

ALTER TABLE fd.thread_guards ADD COLUMN warning_removed_at timestamptz;

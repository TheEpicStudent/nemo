INSERT INTO fd.log_cursors (name, last_id)
VALUES ('public_audit', coalesce((SELECT max(id) FROM fd.audit), 0))
ON CONFLICT (name) DO NOTHING;

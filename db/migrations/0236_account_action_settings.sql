INSERT INTO fd.app_settings (key, value, changed_at)
VALUES ('nemo.deactivate', 'on', now()),
       ('nemo.session_reset', 'on', now())
ON CONFLICT (key) DO NOTHING;

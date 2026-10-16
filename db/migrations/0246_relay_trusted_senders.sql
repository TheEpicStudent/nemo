INSERT INTO fd.app_settings (key, value, changed_at)
VALUES ('relay.trusted_senders', 'U0AKQNSKBK4', now())
ON CONFLICT (key) DO NOTHING;

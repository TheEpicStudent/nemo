INSERT INTO fd.app_settings (key, value, changed_by, changed_at)
SELECT copied.key, firehouse.value, firehouse.changed_by, now()
FROM fd.app_settings firehouse
CROSS JOIN (VALUES ('nemo.reports_channel'), ('nemo.log_channel')) AS copied(key)
WHERE firehouse.key = 'nemo.firehouse_channel'
ON CONFLICT (key) DO NOTHING;

ALTER TABLE fd.case_reports ADD COLUMN IF NOT EXISTS card_channel_id text;

UPDATE fd.case_reports
SET card_channel_id = (SELECT value FROM fd.app_settings WHERE key = 'nemo.firehouse_channel')
WHERE forwarded_ts IS NOT NULL AND card_channel_id IS NULL;

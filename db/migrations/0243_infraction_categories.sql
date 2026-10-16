CREATE TABLE fd.infraction_categories (
    key text PRIMARY KEY,
    label text NOT NULL,
    position integer NOT NULL,
    retired_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT infraction_categories_key_format CHECK (key ~ '^[a-z][a-z0-9_]*$'),
    CONSTRAINT infraction_categories_label_present CHECK (btrim(label) <> '')
);

INSERT INTO fd.infraction_categories (key, label, position) VALUES
    ('nos', 'Misconduct not otherwise specified', 1),
    ('adult', 'Adult', 2),
    ('insulting', 'Insulting or demeaning remarks', 3),
    ('bullying', 'Bullying', 4),
    ('discrimination', 'Discrimination', 5),
    ('hateful', 'Hateful remarks', 6),
    ('harassment_identity', 'Systematic harassment, identity based', 7),
    ('harassment_general', 'Systematic harassment, general', 8),
    ('unwanted_dms', 'Unwanted DMs or personal questions', 9),
    ('private_info', 'Exposing private information', 10),
    ('impersonation', 'Impersonation', 11),
    ('nsfw_mild', 'Mild or ambiguous NSFW', 12),
    ('nsfw_extreme', 'Clear and extreme NSFW', 13),
    ('disruption', 'Disruption or trolling', 14),
    ('advertising', 'Advertising or recruiting', 15),
    ('spam', 'Spam, mass pings or invites', 16),
    ('bot_misuse', 'Bot or automation misuse', 17),
    ('fraud_hcb', 'HCB fraud', 18),
    ('fraud_referral', 'Referral fraud', 19),
    ('fraud_ysws', 'YSWS fraud', 20),
    ('fraud_other', 'Other fraud', 21),
    ('ban_evasion', 'Slack ban evasion', 22);

CREATE OR REPLACE FUNCTION fd.infraction_category_changed() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('fd_infraction_category', '');
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER infraction_categories_changed
    AFTER INSERT OR UPDATE OR DELETE ON fd.infraction_categories
    FOR EACH STATEMENT EXECUTE FUNCTION fd.infraction_category_changed();

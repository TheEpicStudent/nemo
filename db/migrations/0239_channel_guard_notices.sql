ALTER TABLE fd.channel_guards
    ADD COLUMN notice_wanted boolean NOT NULL DEFAULT false,
    ADD COLUMN notice_ts text,
    ADD COLUMN notice_attempts integer NOT NULL DEFAULT 0;

CREATE INDEX channel_guards_notice_wanted
    ON fd.channel_guards (id)
    WHERE notice_wanted;

CREATE TABLE fd.case_card_posts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id bigint NOT NULL REFERENCES fd.cases(id) ON DELETE CASCADE,
    channel_id text NOT NULL,
    message_ts text NOT NULL,
    digest text NOT NULL,
    posted_by text,
    posted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (channel_id, message_ts)
);

CREATE INDEX case_card_posts_case_idx ON fd.case_card_posts (case_id, id DESC);

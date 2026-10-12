CREATE TABLE IF NOT EXISTS fd.member_link_shadow (
    variant     text         NOT NULL,
    a_user_id   text         NOT NULL,
    b_user_id   text         NOT NULL,
    score       numeric(8,3) NOT NULL,
    top_signal  text,
    top_family  text,
    families    jsonb        NOT NULL DEFAULT '{}'::jsonb,
    signals     jsonb        NOT NULL DEFAULT '{}'::jsonb,
    label       text,
    first_seen  timestamptz,
    last_seen   timestamptz,
    computed_at timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (variant, a_user_id, b_user_id),
    CONSTRAINT member_link_shadow_ordered CHECK (a_user_id < b_user_id),
    CONSTRAINT member_link_shadow_score_positive CHECK (score > 0)
);

CREATE INDEX IF NOT EXISTS member_link_shadow_score_idx ON fd.member_link_shadow (variant, score DESC);

CREATE TABLE IF NOT EXISTS fd.link_sample (
    id         bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    variant    text         NOT NULL DEFAULT 'live',
    a_user_id  text         NOT NULL,
    b_user_id  text         NOT NULL,
    band       text         NOT NULL,
    top_signal text,
    score      numeric(8,3) NOT NULL,
    drawn_at   timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT link_sample_pair_key UNIQUE (variant, a_user_id, b_user_id),
    CONSTRAINT link_sample_ordered CHECK (a_user_id < b_user_id),
    CONSTRAINT link_sample_band_known CHECK (band IN ('certain', 'strong', 'weak'))
);

CREATE INDEX IF NOT EXISTS link_sample_pair_idx ON fd.link_sample (a_user_id, b_user_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON fd.member_link_shadow, fd.link_sample TO pipeline_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rails_app') THEN
        GRANT SELECT ON fd.member_link_shadow, fd.link_sample TO rails_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dbt_owner') THEN
        REVOKE ALL ON fd.member_link_shadow, fd.link_sample FROM dbt_owner;
    END IF;
END
$$;

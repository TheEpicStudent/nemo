CREATE TABLE fd.tags (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tags_name_shape CHECK (name ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT tags_name_length CHECK (char_length(name) <= 40)
);

CREATE UNIQUE INDEX tags_name_key ON fd.tags (name);

CREATE TABLE fd.case_tags (
    case_id bigint NOT NULL REFERENCES fd.cases(id) ON DELETE CASCADE,
    tag_id bigint NOT NULL REFERENCES fd.tags(id) ON DELETE RESTRICT,
    added_by text NOT NULL,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, tag_id)
);

CREATE INDEX case_tags_tag_idx ON fd.case_tags (tag_id, case_id);

CREATE TABLE fd.slack_usergroups (
    usergroup_id text PRIMARY KEY,
    handle text NOT NULL,
    name text,
    refreshed_at timestamptz NOT NULL DEFAULT now()
);

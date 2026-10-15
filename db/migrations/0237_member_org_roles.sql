ALTER TABLE fd.member
    ADD COLUMN is_org_admin boolean NOT NULL DEFAULT false,
    ADD COLUMN is_org_owner boolean NOT NULL DEFAULT false;

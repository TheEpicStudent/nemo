UPDATE fd.member_link_verdict
SET verdict = 'different_people',
    note = CASE WHEN note IS NULL OR btrim(note) = '' THEN 'Household' ELSE note || ' (household)' END
WHERE verdict = 'household';

ALTER TABLE fd.member_link_verdict DROP CONSTRAINT member_link_verdict_known;
ALTER TABLE fd.member_link_verdict ADD CONSTRAINT member_link_verdict_known
    CHECK (verdict IN ('same_person', 'different_people', 'allowed_alt'));

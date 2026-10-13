ALTER TABLE fd.member_link_verdict DROP CONSTRAINT member_link_verdict_known;
ALTER TABLE fd.member_link_verdict ADD CONSTRAINT member_link_verdict_known
    CHECK (verdict IN ('same_person', 'different_people', 'household', 'allowed_alt')) NOT VALID;

UPDATE fd.member_link_verdict SET verdict = 'allowed_alt' WHERE verdict = 'staff_test';

ALTER TABLE fd.member_link_verdict VALIDATE CONSTRAINT member_link_verdict_known;

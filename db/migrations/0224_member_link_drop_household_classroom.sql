UPDATE fd.member_link
SET label = NULL,
    families = families - 'household' - 'classroom'
WHERE label IN ('household', 'classroom');

ALTER TABLE fd.member_link DROP CONSTRAINT member_link_label_known;
ALTER TABLE fd.member_link ADD CONSTRAINT member_link_label_known
    CHECK (label IN ('staff_test'));

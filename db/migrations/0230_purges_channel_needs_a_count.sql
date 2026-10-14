ALTER TABLE fd.purges
    ADD CONSTRAINT purges_channel_needs_a_count CHECK (member_id IS NOT NULL OR wanted IS NOT NULL);

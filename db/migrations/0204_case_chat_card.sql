ALTER TABLE fd.case_chat DROP CONSTRAINT IF EXISTS case_chat_carried_by_somebody;

ALTER TABLE fd.case_chat ADD CONSTRAINT case_chat_carried_by_somebody
    CHECK (mirrored_as IS NULL OR mirrored_as IN ('user', 'nemo', 'card'));

ALTER TABLE fd.case_chat DROP CONSTRAINT IF EXISTS case_chat_came_from_somewhere;

ALTER TABLE fd.case_chat ADD CONSTRAINT case_chat_came_from_somewhere
    CHECK (ts IS NOT NULL OR source_app <> 'nemo' OR mirrored_as = 'card');

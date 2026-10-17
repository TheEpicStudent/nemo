ALTER TABLE fd.case_reports ADD COLUMN header_digest text;
ALTER TABLE fd.cases ADD COLUMN card_header_digest text;

CREATE TRIGGER actions_changed
    AFTER INSERT OR UPDATE OF reversed_at OR DELETE ON fd.actions
    FOR EACH ROW EXECUTE FUNCTION fd.case_changed();

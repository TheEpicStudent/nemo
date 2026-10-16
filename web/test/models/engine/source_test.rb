require "test_helper"

module Engine
  class SourceTest < ActiveSupport::TestCase
    test "every source declares each field in Source::DECLARED" do
      Source.all.each do |source|
        Source::DECLARED.each do |field|
          value = source.public_send(field)
          if field == "feeds"
            assert_not_nil value, "#{source.key} declares no #{field}"
          else
            assert value.present?, "#{source.key} declares no #{field}"
          end
        end
      end
    end

    test "source cadence and guard and resume and retention are in their allowed sets" do
      Source.all.each do |source|
        assert_includes Source::CADENCES, source.cadence, source.key
        assert_includes Source::GUARDS, source.guard, source.key
        assert_includes Source::RESUMES, source.resume, source.key
        assert_includes Source::RETENTIONS, source.retention, source.key
      end
    end

    test "no source has retention prune" do
      Source.all.each do |source|
        assert_not_equal "prune", source.retention, source.key
      end
    end

    test "SyncRequest::STAGES equals Source::KEYS and includes channel_membership" do
      assert_equal Source::KEYS, SyncRequest::STAGES
      assert_includes SyncRequest::STAGES, "channel_membership", "channel_membership is a valid stage"
    end

    test "SyncRequest with an unknown stage is invalid" do
      request = SyncRequest.new(kind: "stage", stage: "teleporter", requested_by: "UME")

      assert_not request.valid?
      assert_includes request.errors[:stage], "is not included in the list"
    end

    test "Source lookup with an unknown key raises UnknownError" do
      assert_raises(Source::UnknownError) { Source["teleporter"] }
      assert_raises(Source::UnknownError) { Source["team_stats"].limit(:batch) }
    end

    test "guarded? and resumable? reflect the declared guard and resume" do
      assert Source["member_range"].guarded?
      assert_not Source["team_stats"].guarded?
      assert Source["users_list"].resumable?
      assert_not Source["team_stats"].resumable?
    end
  end
end

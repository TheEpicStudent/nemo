require "test_helper"

class FdTranscriptsTest < ActionDispatch::IntegrationTest
  setup do
    @transcript = Fd::ThreadTranscript.create!(
      channel_id: "C0BAHBV008Z", thread_ts: "1788927328.716919",
      body: "[2026-09-22T16:11:22.170Z] <USLACKBOT|Slackbot> This message was deleted.\n"
    )
    @key = "C0BAHBV008Z_1788927328.716919"
  end

  test "show signed out redirects without the transcript body" do
    get destroy_transcript_path(key: @key)
    assert_response :redirect
    assert_not_equal @transcript.body, response.body
  end

  test "show for gardener role redirects without the transcript body" do
    sign_in_as(grant_role!("UNOBODY", "gardener"))
    get destroy_transcript_path(key: @key)
    assert_response :redirect
    assert_not_equal @transcript.body, response.body
  end

  test "show for firefighter returns the transcript as plain text with nosniff and no-store" do
    sign_in_as(grant_role!("UFIRE", "firefighter"))
    get destroy_transcript_path(key: @key)

    assert_response :success
    assert_equal @transcript.body, response.body
    assert_match "text/plain", response.media_type.to_s + response.headers["Content-Type"].to_s
    assert_equal "nosniff", response.headers["X-Content-Type-Options"]
    assert_equal "private, no-store", response.headers["Cache-Control"]
  end

  test "show for community manager returns success" do
    sign_in_as(grant_role!("UBOSS", "community_manager"))
    get destroy_transcript_path(key: @key)
    assert_response :success
  end

  test "show writes one read audit entry" do
    sign_in_as(grant_role!("UFIRE2", "firefighter"))
    assert_difference -> { Fd::AuditEntry.where(verb: "read").count }, 1 do
      get destroy_transcript_path(key: @key)
    end
  end

  test "show with malformed key returns 404 or a redirect without the transcript body" do
    sign_in_as(grant_role!("UFIRE3", "firefighter"))
    ["../../etc/passwd", "C0BAHBV008Z", "notachannel_1.2", "C0BAHBV008Z_abc"].each do |bad|
      get "/cdn/destroy/#{bad}"
      assert_includes [404, 301, 302], response.status, bad
      assert_not_equal @transcript.body, response.body, bad
    end
  end

  test "show with key of a missing transcript returns 404" do
    sign_in_as(grant_role!("UFIRE4", "firefighter"))
    get destroy_transcript_path(key: "C0BAHBV008Z_1700000000.000001")
    assert_response :not_found
  end
end

require "test_helper"

class Fd::MemberLinkBroadcastTest < ActiveSupport::TestCase
  include ActionCable::TestHelper

  test "of with * broadcasts reload_frame to LIST_STREAM" do
    sent = capture_broadcasts(Fd::MemberLinkBroadcast::LIST_STREAM) { Fd::MemberLinkBroadcast.of("*") }

    assert_equal [%(<turbo-stream action="reload_frame" target="member-links-list"></turbo-stream>)], sent
  end

  test "of with a member id broadcasts refresh_frame to that member stream" do
    sent = capture_broadcasts(Fd::MemberLinkBroadcast.stream("UONE")) { Fd::MemberLinkBroadcast.of("uone") }

    assert_equal [%(<turbo-stream action="refresh_frame" target="member-links-UONE"></turbo-stream>)], sent
  end

  test "of with an invalid payload returns nil and broadcasts nothing" do
    assert_no_broadcasts(Fd::MemberLinkBroadcast.stream("NOPE")) do
      assert_nil Fd::MemberLinkBroadcast.of("not a member")
    end
  end

  test "ChatListener::CHANNELS includes fd_member_link" do
    assert_includes Fd::ChatListener::CHANNELS, "fd_member_link"
  end
end

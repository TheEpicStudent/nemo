require "test_helper"

class Fd::ChannelJoinRequestTest < ActiveSupport::TestCase
  def queue_request(channel_id = "C0PUBLIC")
    Fd::ChannelJoinRequest.queue!(channel_id: channel_id, requested_by: "UME")
  end

  test "queue! twice for one channel returns the same queued request" do
    first = queue_request
    second = queue_request

    assert_equal first.id, second.id
    assert_equal 1, Fd::ChannelJoinRequest.queued.count
  end

  test "queue! after a finished request creates a new request" do
    first = queue_request
    first.update!(state: Fd::ChannelJoinRequest::JOINED, finished_at: Time.current)

    assert_not_equal first.id, queue_request.id
  end

  test "wait_for returns a finished request in under one second" do
    join_request = queue_request
    join_request.update!(state: Fd::ChannelJoinRequest::REFUSED, error: "is_archived",
      finished_at: Time.current)

    started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    answered = Fd::ChannelJoinRequest.wait_for(join_request, timeout: 5)

    assert_equal "is_archived", answered.error
    assert_operator Process.clock_gettime(Process::CLOCK_MONOTONIC) - started, :<, 1
  end

  test "wait_for returns the queued request after the timeout" do
    answered = Fd::ChannelJoinRequest.wait_for(queue_request, timeout: 0.3)

    assert_predicate answered, :queued?
  end
end

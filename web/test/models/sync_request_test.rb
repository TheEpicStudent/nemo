require "test_helper"

class SyncRequestTest < ActiveSupport::TestCase
  def claimed(status:)
    SyncRequest.create!(kind: "full", requested_by: "UTEST1", status: status, claimed_at: Time.current)
  end

  test "cancel! on claimed request returns true and sets status cancelling" do
    request = claimed(status: "claimed")

    assert request.cancel!
    assert_equal "cancelling", request.status
  end

  test "cancel! on cancelling request returns true and keeps status cancelling" do
    request = claimed(status: "cancelling")

    assert request.cancel!, "second cancel! returns true"
    assert_equal "cancelling", request.status
  end

  test "cancel! with worker_unavailable on cancelling request sets cancelled and finished_at" do
    request = claimed(status: "cancelling")

    assert request.cancel!(worker_unavailable: true)
    assert_equal "cancelled", request.status
    assert request.finished_at.present?
  end

  test "cancel! with worker_unavailable on claimed request sets cancelled" do
    request = claimed(status: "claimed")

    assert request.cancel!(worker_unavailable: true)
    assert_equal "cancelled", request.status
  end

  test "cancel! on queued request sets status cancelled" do
    request = claimed(status: "queued")

    assert request.cancel!
    assert_equal "cancelled", request.status
  end

  test "cancel! on done request returns false" do
    request = claimed(status: "done")

    assert_not request.cancel!
  end
end

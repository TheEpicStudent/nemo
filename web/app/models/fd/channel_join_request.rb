module Fd
  class ChannelJoinRequest < ApplicationRecord
    self.table_name = "fd.channel_join_requests"

    QUEUED = "queued".freeze
    JOINED = "joined".freeze
    REFUSED = "refused".freeze

    WAIT_SECONDS = 6
    POLL_SECONDS = 0.25

    scope :queued, -> { where(state: QUEUED) }

    def self.queue!(channel_id:, requested_by:)
      queued.find_by(channel_id: channel_id) ||
        create!(channel_id: channel_id, requested_by: requested_by)
    rescue ActiveRecord::RecordNotUnique
      queued.find_by!(channel_id: channel_id)
    end

    def self.wait_for(join_request, timeout: WAIT_SECONDS)
      deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + timeout
      loop do
        join_request.reload
        return join_request unless join_request.queued?
        return join_request if Process.clock_gettime(Process::CLOCK_MONOTONIC) >= deadline

        sleep POLL_SECONDS
      end
    end

    def queued? = state == QUEUED

    def joined? = state == JOINED
  end
end

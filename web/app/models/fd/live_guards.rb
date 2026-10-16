module Fd
  class LiveGuards
    def initialize(requested_kind = nil)
      @kind = ChannelGuard.kind?(requested_kind) ? requested_kind : nil
    end

    attr_reader :kind

    def rows
      @rows ||= kind ? sorted.select { |guard| guard.kind == kind } : sorted
    end

    def tally
      @tally ||= sorted.group_by(&:kind).transform_values(&:size)
    end

    def total = sorted.size

    def any? = rows.any?

    def allowed(guard) = allow_counts[guard.id].to_i

    def channels
      sorted
      @channels
    end

    def opener_user_ids = sorted.map(&:opened_by)

    private

    def sorted
      @sorted ||= begin
        guards = ChannelGuard.live.channel_wide.to_a
        @channels = ChannelNames.for(guards.map(&:channel_id))
        guards.sort_by { |guard|
          [ChannelGuard::KINDS.index(guard.kind) || ChannelGuard::KINDS.size,
           @channels[guard.channel_id]]
        }
      end
    end

    def allow_counts
      @allow_counts ||= ChannelGuardAllow.where(guard_id: rows.map(&:id))
        .group(:guard_id).count
    end
  end
end

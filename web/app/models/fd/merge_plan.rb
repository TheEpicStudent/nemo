module Fd
  class MergePlan
    def self.for(from, into, primary: nil)
      new([from, into], primary: primary)
    end

    def self.over(cases, primary: nil)
      new(cases, primary: primary)
    end

    def initialize(all, primary: nil)
      @all = Array(all).compact.uniq(&:id)
      @requested_primary_id = primary
    end

    attr_reader :all

    def from
      all.first
    end

    def into
      all.last
    end

    def pair?
      all.size == 2
    end

    def primary
      @primary ||= all.find { |kase| kase.id == @requested_primary_id.to_i } || all.min_by(&:opened_at)
    end

    def merged_cases
      @merged_cases ||= all.reject { |kase| kase.id == primary.id }
    end

    def merged
      merged_cases.first
    end

    def reports = both { |kase| kase.reports.size }

    def threads = both { |kase| kase.threads.size }

    def actions = both { |kase| kase.actions.size }

    def notes = both { |kase| kase.notes.visible.size }

    def participant_count
      all.flat_map { |kase| kase.participants.map(&:user_id) }.uniq.size
    end

    private

    def both(&block)
      all.sum(&block)
    end
  end
end

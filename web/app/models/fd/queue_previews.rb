module Fd
  class QueuePreviews
    attr_reader :cited, :attachment_counts, :roots

    def self.for(cases)
      new(cases)
    end

    def initialize(cases)
      ids = cases.map(&:id)
      @cases = cases
      @cited = IntakeShare.first_shares_for(ids)
      @attachment_counts = IntakeFile.counts_for_cases(ids)
      @roots = CaseChat.roots_for(cases.select { |kase| kase.reports.empty? })
    end

    def user_ids
      bodies.flat_map { |body| Mentions.ids(body) } + cited.values.map(&:author) +
        roots.values.map(&:author_user_id)
    end

    def channel_ids
      bodies.flat_map { |body| Mentions.channel_ids(body) } + cited.values.map(&:channel)
    end

    private

    def bodies
      @bodies ||= @cases.filter_map { |kase| kase.reports.min_by(&:received_at)&.body } +
        cited.values.map(&:body) + roots.values.map(&:body)
    end
  end
end

module Channels
  class Map
    SHOWN = 80

    QUADRANTS = {
      high_high: ["working", 2],
      high_low: ["landing, not staying", 4],
      low_high: ["small and sticky", 1],
      low_low: ["quiet", 0]
    }.freeze

    Point = Struct.new(:channel_id, :name, :x, :y, :n, :ink, :phase, keyword_init: true) do
      def as_json(*)
        { name: name, x: x, y: y, n: n, ink: ink, phase: phase }
      end
    end

    Reach = Struct.new(:cohort_size, :searched, :cohort_start, :cohort_end, keyword_init: true)

    Report = Struct.new(:points, :x_mid, :y_mid, :reach, :floor, keyword_init: true) do
      def any? = points.any?

      def phases
        points.map { |p| [p.phase, p.ink] }.uniq.sort_by { |_, ink| ink }
      end
    end

    def self.floor
      HomeHelper::MIN_SAMPLE
    end

    def self.opportunity
      rows = measured.order(newcomers_posting: :desc).limit(SHOWN).to_a
      whole = Analytics::MartNewcomerChannels.where(newcomers_posting: 1..)
      x_mid = median(rows.map { |r| r.newcomers_posting.to_i })
      y_mid = share_of(whole.sum(:newcomers_returning_anywhere),
        whole.sum(:newcomers_posting))

      points = rows.map do |row|
        x = row.newcomers_posting.to_i
        y = share(row.returning_anywhere_share)
        label, ink = phase(across: x >= x_mid, above: y >= (y_mid || 0))
        Point.new(channel_id: row.channel_id, name: row.name, x: x, y: y,
          n: row.newcomer_messages.to_i, ink: ink, phase: label)
      end

      Report.new(points: points.sort_by { |p| -p.n.to_i }, x_mid: x_mid, y_mid: y_mid,
        reach: reach, floor: floor)
    end

    def self.measured
      Analytics::MartNewcomerChannels
        .where(newcomers_posting: floor..)
        .where.not(returning_anywhere_share: nil)
    end

    def self.phase(across:, above:)
      QUADRANTS.fetch(:"#{across ? "high" : "low"}_#{above ? "high" : "low"}")
    end

    def self.reach
      row = Analytics::MartNewcomerChannels.take
      return nil if row.nil?

      Reach.new(cohort_size: row.cohort_size.to_i, searched: row.searched_of_cohort.to_i,
        cohort_start: row.cohort_start, cohort_end: row.cohort_end)
    end

    def self.share(value)
      value.nil? ? nil : (value.to_f * 100).round(1)
    end

    def self.share_of(part, whole)
      return nil if whole.to_i.zero?

      (part.to_f / whole * 100).round(1)
    end

    def self.median(values)
      seen = values.compact.sort
      return 0 if seen.empty?

      mid = seen.length / 2
      seen.length.odd? ? seen[mid] : ((seen[mid - 1] + seen[mid]) / 2.0)
    end
  end
end

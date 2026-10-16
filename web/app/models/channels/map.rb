module Channels
  class Map
    CHANNEL_LIMIT = 80

    QUADRANTS = {
      high_high: ["high volume, high retention", 2],
      high_low: ["high volume, low retention", 4],
      low_high: ["low volume, high retention", 1],
      low_low: ["low volume, low retention", 0]
    }.freeze

    Point = Struct.new(:channel_id, :name, :x, :y, :n, :series_color, :phase, keyword_init: true) do
      def as_json(*)
        { name: name, x: x, y: y, n: n, seriesColor: series_color, phase: phase }
      end
    end

    Report = Struct.new(:points, :x_mid, :y_mid, :cohort, :floor, keyword_init: true) do
      def any? = points.any?

      def phases
        points.map { |p| [p.phase, p.series_color] }.uniq.sort_by { |_, color_index| color_index }
      end
    end

    def self.floor
      HomeHelper::MIN_SAMPLE
    end

    def self.opportunity(cohort)
      rows = measured(cohort.key).order(newcomers_posting: :desc).limit(CHANNEL_LIMIT).to_a
      cohort_channels = Analytics::MartNewcomerChannels.for_cohort(cohort.key)
        .where(newcomers_posting: 1..)
      x_mid = median(rows.map { |r| r.newcomers_posting.to_i })
      y_mid = share_of(cohort_channels.sum(:newcomers_returning_anywhere),
        cohort_channels.sum(:newcomers_posting))

      points = rows.map do |row|
        x = row.newcomers_posting.to_i
        y = share(row.returning_anywhere_share)
        label, color_index = phase(across: x >= x_mid, above: y >= (y_mid || 0))
        Point.new(channel_id: row.channel_id, name: row.name, x: x, y: y,
          n: row.newcomer_messages.to_i, series_color: color_index, phase: label)
      end

      Report.new(points: points.sort_by { |p| -p.n.to_i }, x_mid: x_mid, y_mid: y_mid,
        cohort: cohort, floor: floor)
    end

    def self.measured(cohort_key)
      Analytics::MartNewcomerChannels
        .for_cohort(cohort_key)
        .where(newcomers_posting: floor..)
        .where.not(returning_anywhere_share: nil)
    end

    def self.phase(across:, above:)
      QUADRANTS.fetch(:"#{across ? "high" : "low"}_#{above ? "high" : "low"}")
    end

    def self.share(value)
      value.nil? ? nil : (value.to_f * 100).round(1)
    end

    def self.share_of(part, total)
      return nil if total.to_i.zero?

      (part.to_f / total * 100).round(1)
    end

    def self.median(values)
      sorted = values.compact.sort
      return 0 if sorted.empty?

      mid = sorted.length / 2
      sorted.length.odd? ? sorted[mid] : ((sorted[mid - 1] + sorted[mid]) / 2.0)
    end
  end
end

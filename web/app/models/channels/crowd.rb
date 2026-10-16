module Channels
  class Crowd
    TOP_LIMIT = 10
    MONTHS_OFFERED = 12

    TENURE = {
      "under_90d" => "under 90 days",
      "under_1y" => "90 days to a year",
      "under_3y" => "one to three years",
      "over_3y" => "over three years",
      "unknown" => "join date unknown"
    }.freeze

    TENURE_ORDER = TENURE.keys.freeze

    Slice = Struct.new(:key, :label, :people, :messages, :share, keyword_init: true)
    Part = Struct.new(:key, :label, :people, :share, keyword_init: true)

    attr_reader :channel_id, :month

    def self.for(channel_id, month: nil)
      new(channel_id, month: month)
    end

    def initialize(channel_id, month: nil)
      @channel_id = channel_id
      @month = months.include?(month) ? month : months.first
    end

    def months
      @months ||= Analytics::MartChannelPerson
        .where(channel_id: channel_id)
        .distinct.order(month: :desc).limit(MONTHS_OFFERED).pluck(:month)
    end

    def any?
      month.present?
    end

    def person_rows
      @person_rows ||= Analytics::MartChannelPerson.where(channel_id: channel_id, month: month)
    end

    def head
      @head ||= person_rows.order(:channel_rank).first
    end

    def posters = head&.channel_posters.to_i
    def messages = head&.channel_messages.to_i
    def month_end = head&.month_end

    def top(limit: TOP_LIMIT)
      @top ||= {}
      @top[limit] ||= person_rows.order(:channel_rank).limit(limit).to_a
    end

    def tenure
      @tenure ||= begin
        band_counts = person_rows.group(:tenure_band)
          .pluck(Arel.sql("tenure_band, count(*), coalesce(sum(messages), 0)"))
          .to_h { |band, member_count, messages| [band, [member_count.to_i, messages.to_i]] }
        total_messages = band_counts.values.sum { |_, messages| messages }

        TENURE_ORDER.filter_map do |band|
          member_count, messages = band_counts[band]
          next if member_count.nil? || messages.to_i.zero?

          Slice.new(key: band, label: TENURE.fetch(band), people: member_count, messages: messages,
            share: total_messages.positive? ? (messages * 100.0 / total_messages).round(1) : nil)
        end
      end
    end

    def composition(range)
      return [] if range.nil?

      members = range.total_members.to_i
      return [] unless members.positive?

      poster_count = range.members_who_posted.to_i.clamp(0, members)
      viewer_count = range.members_who_viewed.to_i.clamp(poster_count, members)
      read_only_count = viewer_count - poster_count
      never_viewed_count = members - viewer_count

      [["spoke", "posted", poster_count], ["read", "read only", read_only_count],
       ["never", "never viewed", never_viewed_count]].map do |key, label, member_count|
        Part.new(key: key, label: label, people: member_count,
          share: (member_count * 100.0 / members).round(1))
      end
    end

    def curve
      @curve ||= Analytics::MartChannelConcentration
        .where(channel_id: channel_id, month: month).order(:poster_pct).to_a
    end

    def concentration
      curve.first
    end

    def gini
      concentration&.gini&.to_f
    end

    def half_mark
      curve.find { |point| point.message_pct.to_f >= 50 }
    end
  end
end

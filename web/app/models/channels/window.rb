module Channels
  class Window
    PRESETS = [7, 30, 90].freeze

    LOADED_SQL = "#{Joins::RANGE}.messages_posted_by_members".freeze
    ROLLED_SQL = "#{Joins::ROLLUP}.range_messages".freeze

    attr_reader :days, :start_date, :end_date, :loaded_start, :loaded_end, :edge

    def self.from(params)
      lo, hi = loaded_bounds
      new(days: params[:days], start_on: on(params[:start]), end_on: on(params[:end]),
          loaded_start: lo, loaded_end: hi,
          edge: Analytics::MartChannelActivity.maximum(:window_start))
    end

    def self.on(value)
      Date.iso8601(value.to_s)
    rescue ArgumentError
      nil
    end

    def self.loaded_bounds
      row = Analytics::MartChannelRange
        .select("min(window_start) AS lo, max(window_end) AS hi").take
      [row&.lo, row&.hi]
    end

    def initialize(days:, loaded_start:, loaded_end:, edge:, start_on: nil, end_on: nil)
      @loaded_start = loaded_start
      @loaded_end = loaded_end
      @edge = edge
      @custom = resolve_custom_range(start_on, end_on)
      if @custom
        @days = (@end_date - @start_date).to_i + 1
        return
      end

      @days = resolve_days(days)
      @end_date = loaded? ? @loaded_end : @edge
      @start_date = loaded? ? @loaded_start : (@edge && @edge - (@days - 1))
    end

    def custom?
      @custom
    end

    def floor
      [@loaded_start, @edge && (@edge - 400)].compact.max
    end

    def ceiling
      [@edge, @loaded_end].compact.max
    end

    def loaded_days
      return nil if @loaded_start.nil? || @loaded_end.nil?

      (@loaded_end - @loaded_start).to_i + 1
    end

    def choices
      ([loaded_days] + PRESETS).compact.uniq.sort
    end

    def loaded?
      return false if @custom

      @edge.nil? || @days == loaded_days
    end

    def adjustable?
      @edge.present? && choices.many?
    end

    def join
      return nil if loaded?

      ActiveRecord::Base.sanitize_sql_array(
        ["LEFT JOIN (SELECT channel_id, sum(messages_posted_by_members) AS range_messages " \
         "FROM analytics.mart_channel_activity " \
         "WHERE window_start BETWEEN ? AND ? GROUP BY channel_id) #{Joins::ROLLUP} " \
         "ON #{Joins::ROLLUP}.channel_id = #{Joins::SPINE}.channel_id", @start_date, @end_date]
      )
    end

    def measure_sql
      loaded? ? LOADED_SQL : ROLLED_SQL
    end

    def column
      loaded? ? "#{LOADED_SQL} AS range_messages" : ROLLED_SQL
    end

    def measures
      loaded? ? {} : { "messages" => ROLLED_SQL }
    end

    def requested_days
      @days unless loaded? || @custom
    end

    def requested_start
      @start_date if @custom
    end

    def requested_end
      @end_date if @custom
    end

    private

    def resolve_custom_range(start_on, end_on)
      return false if start_on.nil? && end_on.nil?

      low, high = floor, ceiling
      return false if low.nil? || high.nil?

      @end_date = (end_on || high).clamp(low, high)
      @start_date = (start_on || @end_date).clamp(low, @end_date)
      true
    end

    def resolve_days(requested)
      requested_days = requested.to_i
      return requested_days if choices.include?(requested_days)

      loaded_days || PRESETS.min
    end
  end
end

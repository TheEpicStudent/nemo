module HomeHelper
  MIN_SAMPLE = 20
  GROWTH_SPANS = [6, 12, 24].freeze
  DEFAULT_GROWTH_SPAN = 6

  def date_range_label(from, to)
    return "" if from.nil? || to.nil?

    start_label = from.strftime(from.year == to.year ? "%b %-d" : "%b %-d, %Y")
    "#{start_label} - #{to.strftime('%b %-d, %Y')}"
  end

  def window_note(from, to)
    return nil if from.nil? || to.nil?

    return to.strftime("%-d %b %Y") if from == to

    same_year = from.year == to.year
    "#{from.strftime(same_year ? '%-d %b' : '%-d %b %Y')} to #{to.strftime('%-d %b %Y')}"
  end

  OVERVIEW_SPANS = {
    "7d" => { label: "7 days", days: 7, granularity: "daily" },
    "30d" => { label: "30 days", days: 30, granularity: "daily" },
    "90d" => { label: "90 days", days: 90, granularity: "daily" },
    "12m" => { label: "12 months", months: 12, granularity: "monthly" }
  }.freeze
  DEFAULT_OVERVIEW_SPAN = "30d".freeze

  def overview_span(value)
    OVERVIEW_SPANS.key?(value.to_s) ? value.to_s : DEFAULT_OVERVIEW_SPAN
  end

  def span_of(key)
    OVERVIEW_SPANS.fetch(overview_span(key))
  end

  def activity_series(rows, granularity)
    if granularity == "monthly"
      {
        labels: rows.map { |row| row.month.strftime("%b %Y") },
        days: false,
        span: "#{rows.size} months",
        partial: rows.each_with_index.filter_map { |row, i| i unless row.is_complete },
        active: rows.map(&:active_users_28d),
        posted: rows.map(&:writers_count_28d),
        posted_label: "posted",
        silent: rows.map { |row| row.active_users_28d.to_i - row.writers_count_28d.to_i },
        silent_label: "active, not posted",
        posted_share: rows.map { |row| share_pct(row.writers_count_28d, row.active_users_28d) },
        messages: rows.map(&:channel_messages),
        public: rows.map(&:public_channel_messages),
        public_label: "public channels",
        private: rows.map { |row| row.channel_messages.to_i - row.public_channel_messages.to_i },
        private_label: "private channels",
        public_share: rows.map { |row| share_pct(row.public_channel_messages, row.channel_messages) }
      }
    else
      {
        labels: rows.map { |row| row.ds.iso8601 },
        days: true,
        span: "#{rows.size} days",
        partial: [],
        active: rows.map(&:active_users_1d),
        posted: rows.map(&:writers_count_1d),
        posted_label: "posted",
        silent: rows.map { |row| row.active_users_1d.to_i - row.writers_count_1d.to_i },
        silent_label: "active, not posted",
        posted_share: rows.map { |row| share_pct(row.writers_count_1d, row.active_users_1d) },
        messages: rows.map(&:channel_messages_1d),
        public: rows.map(&:chats_channels_count_1d),
        public_label: "public channels",
        private: rows.map { |row| row.channel_messages_1d.to_i - row.chats_channels_count_1d.to_i },
        private_label: "private channels",
        public_share: rows.map { |row| share_pct(row.chats_channels_count_1d, row.channel_messages_1d) }
      }
    end
  end

  def stat_delta(current, prior)
    return nil if current.nil? || prior.nil? || prior.to_f.zero?

    ((current.to_f - prior.to_f) / prior.to_f * 100).round(1)
  end

  def delta_chip(current, prior)
    pct = stat_delta(current, prior)
    return nil if pct.nil? || pct.abs < 0.05

    delta_tag(pct)
  end

  DELTA_DIRECTIONS = {
    "up" => ["m18 15-6-6-6 6", "up"],
    "down" => ["m6 9 6 6 6-6", "down"],
    "flat" => ["M5 12h14", "no change"]
  }.freeze

  def delta_tag(pct)
    direction = pct.positive? ? "up" : pct.negative? ? "down" : "flat"
    path, direction_label = DELTA_DIRECTIONS.fetch(direction)
    tag.span(class: "delta delta-#{direction}") do
      safe_join([
        tag.svg(viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2,
          "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true") { tag.path(d: path) },
        tag.span(direction_label, class: "visually-hidden"),
        number_to_percentage(pct.abs, precision: 1)
      ])
    end
  end

  REPLY_CLASS_LABEL = {
    "fast" => "under 1 h",
    "slow" => "over 1 h",
    "none" => "no member reply"
  }.freeze

  def reply_class_label(reply_class)
    REPLY_CLASS_LABEL.fetch(reply_class, reply_class)
  end

  def retention_cell(rate)
    return tag.span("n/a", class: "sub2") if rate.nil?

    number_to_percentage((rate.to_f * 100).round(1), precision: 1)
  end

  def reply_wait(seconds)
    return tag.span("n/a", class: "sub2") if seconds.nil?

    seconds = seconds.to_i
    return "#{seconds}s" if seconds < 90

    minutes = seconds / 60
    return "#{minutes} min" if minutes < 90

    hours = minutes / 60.0
    return format("%.1f h", hours) if hours < 48

    format("%.1f d", hours / 24)
  end

  WINDOWS = [[86_400, "day"], [3600, "hour"], [60, "minute"]].freeze

  def window_label(seconds)
    return "the whole span" if seconds.blank?

    size, word = WINDOWS.find { |step, _| seconds >= step } || [1, "second"]
    count = (seconds.to_f / size).round
    "the first #{count == 1 ? word : pluralize(count, word)}"
  end

  def share_pct(numerator, denominator)
    return nil if denominator.nil? || denominator.to_i.zero? || numerator.nil?

    ((numerator.to_f / denominator) * 100).round(1)
  end

  HEAT_STEPS = 6

  def heat_step(value, peak)
    return 0 if value.nil? || peak.nil? || peak.to_f <= 0

    [[(value.to_f / peak * (HEAT_STEPS - 1)).round, 0].max, HEAT_STEPS - 1].min
  end

  def lifecycle_cell(row, stage, peak)
    value = row.public_send(stage[:key])
    return heat_cell(row, stage, peak) if value

    if lifecycle_open?(row, stage)
      tag.span("Pending", class: "lg-cell lg-open")
    else
      tag.span("n/a", class: "lg-cell lg-none")
    end
  end

  def heat_cell(row, stage, peak)
    value = row.public_send(stage[:key])
    cell_class = "lg-cell lg-h#{heat_step(value, peak)}"

    if stage[:prev] == :invited
      return tag.span(number_to_percentage(value.to_f * 100, precision: 1),
        class: cell_class)
    end

    step = row.step_of(stage)
    tag.span(class: "#{cell_class} lg-two") do
      concat tag.b(step ? number_to_percentage(step * 100, precision: 1) : "n/a")
      concat tag.span("#{number_to_percentage(value.to_f * 100, precision: 1)} of created")
    end
  end

  def lifecycle_open?(row, stage)
    case stage[:key]
    when :signed_rate then false
    when :posted_rate_30d then Date.current < row.closes_on(:posted_rate_30d)
    when :funnel_30 then Date.current < row.closes_on(:funnel_30)
    when :funnel_90 then Date.current < row.closes_on(:funnel_90)
    end
  end

  def band_split(value, bands, label)
    return nil if value.nil?

    position = bands.index { |band| (band.band_top || Float::INFINITY) >= value.to_i }
    return nil if position.nil? || position >= bands.size - 1

    { after: position, label: "#{label} #{number_with_delimiter(value)}" }
  end

  def wilson_bounds(hits, sample)
    return nil if sample.nil? || sample.to_i.zero?

    z = 1.96
    p = hits.to_f / sample
    d = 1 + (z**2 / sample)
    centre = (p + (z**2 / (2.0 * sample))) / d
    margin = z * Math.sqrt((p * (1 - p) / sample) + (z**2 / (4.0 * sample**2))) / d
    [[centre - margin, 0].max * 100, [centre + margin, 1].min * 100]
  end
end

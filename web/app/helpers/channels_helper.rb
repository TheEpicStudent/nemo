module ChannelsHelper
  def channel_query(**overrides)
    base = { q: @q.presence, sort: @sort, direction: @direction,
             days: @window&.requested_days,
             start: @window&.requested_start,
             end: @window&.requested_end,
             match: (@filter.match if @filter&.any?),
             c: (@filter.to_params.values if @filter&.any?),
             measure: (@measure unless @measure == @default_measure),
             cohort: (@cohort&.iso8601 unless @cohort == @default_cohort),
             newcomers: (@newcomer_cohort&.key unless @newcomer_cohort&.default?) }
    channels_path(**base.merge(overrides).compact)
  end

  def channels_empty_title
    return "No matches" if @q.present?
    return "No matches" if @filter&.any?
    return "No channels" if @visible_total.to_i.zero?

    "No channels"
  end

  def backfill_cost(channel, estimate, ceiling)
    lines = ["Fetch thread replies for ##{channel.name}?",
             "Estimated requests: #{number_with_delimiter(estimate)}."]
    lines << "Over the limit of #{number_with_delimiter(ceiling)}." if estimate > ceiling
    lines.join(" ")
  end

  def band_title(row)
    "Channels by #{row.measure_label}"
  end

  FUNNEL_SHORT = {
    "landed" => "first post",
    "answered" => "replied",
    "fast" => "fast reply",
    "returned" => "returned"
  }.freeze

  def funnel_step_label(step)
    FUNNEL_SHORT.fetch(step.key, step.label).to_s.upcase_first
  end

  def latency_bucket_label(bucket)
    bucket.to_s.sub(/\Aunder /, "<").sub(/\Aover /, ">").gsub(" to ", "-")
  end

  def channel_sort_th(label, column, css = nil)
    active = @sort == column
    next_direction = active ? (@direction == "asc" ? "desc" : "asc") : "desc"
    arrow = active ? (@direction == "asc" ? " &uarr;" : " &darr;") : ""
    sort_state = active ? (@direction == "asc" ? "ascending" : "descending") : "none"

    tag.th(class: css, **{ "aria-sort": sort_state }) do
      link_to safe_join([label, arrow.html_safe]),
        channel_query(sort: column, direction: next_direction),
        class: "sortable", data: { turbo_frame: "channels" }
    end
  end

  def time_ago_parts(time)
    label = time_ago(time)
    return nil if label.nil?

    parts = label.match(/\A(\d[\w.]*)\s+(.+)\z/)
    return label if parts.nil?

    safe_join([parts[1], tag.small(" #{parts[2]}")])
  end

  def channel_change_cell(channel)
    if channel.try(:prior_thin)
      return tag.span("n/a", class: "sub2")
    end

    change = channel.try(:range_change)
    return tag.span("n/a", class: "sub2") if change.nil?

    change = change.to_f
    tone = change.positive? ? "delta-up" : change.negative? ? "delta-down" : "delta-share"
    tag.span("#{change.positive? ? '+' : ''}#{number_to_percentage(change, precision: 1)}",
      class: tone)
  end

  def slack_window_label(range, from, to)
    stats = range&.stats || {}
    lo = Channels::Window.on(stats["start_date"]) || from
    hi = Channels::Window.on(stats["end_date"]) || to
    window_note(lo, hi)
  end

  def viewable_channel_ids
    @viewable_channel_ids ||=
      Channels::Audience.for(current_account).pluck(:channel_id).to_set
  end

  def channel_name_cell(channel_id, name)
    label = tag.b("##{name}")
    return label unless viewable_channel_ids.include?(channel_id)

    link_to(label, channel_path(channel_id))
  end

  def channel_poster_share(posted, members)
    return "n/a" if posted.nil? || members.to_i.zero?

    number_to_percentage(posted.to_f / members * 100, precision: 1)
  end

  def channel_view_path(**overrides)
    base = { view: (@view unless @view == ChannelsController::DEFAULT_VIEW),
             days: (@range_preset unless @range_preset == ChannelsController::DEFAULT_RANGE_DAYS),
             start: (@start_date if @range_preset.nil?),
             end: (@end_date if @range_preset.nil?),
             month: (@member_counts&.month&.iso8601 unless @member_counts&.month == @member_counts&.months&.first) }
    text = base.merge(overrides)
    text[:view] = nil if text[:view] == ChannelsController::DEFAULT_VIEW
    text = text.except(:start, :end) if text[:days]
    text = text.except(:days) if text[:start] || text[:end]
    channel_path(@channel, **text.compact)
  end

  def pulse_delta(pct, comparison = nil)
    return tag.span("n/a", class: "sub2") if pct.nil?

    safe_join([delta_tag(pct), comparison].compact, " ")
  end

  def duration_label(seconds)
    return "n/a" if seconds.nil?

    seconds = seconds.to_i
    return "#{seconds}s" if seconds < 60
    return "#{seconds / 60}m #{seconds % 60}s" if seconds < 3600
    return "#{seconds / 3600}h #{(seconds % 3600) / 60}m" if seconds < 86_400

    "#{seconds / 86_400}d"
  end

  def channel_standing(standing)
    return nil if standing.nil? || standing.rank.nil?

    active = standing.active_channels.to_i
    return nil unless active.positive?

    { rank: standing.rank, of: active,
      percentile: (100 - ((standing.rank - 1) * 100.0 / active)).floor }
  end

  def concentration_points(curve)
    curve.map { |point| [point.poster_pct, point.message_pct.to_f] }
  end

  def time_ago(time)
    return nil if time.nil?

    gap = (Time.current - time).to_i
    return "just now" if gap < 60
    return "#{gap / 60} min ago" if gap < 3600
    return "#{gap / 3600}h ago" if gap < 86_400
    return "#{gap / 86_400}d ago" if gap < 2_592_000

    time.to_date.strftime("%-d %b %Y")
  end

  def slack_channel_url(channel_id)
    "https://app.slack.com/client/#{ENV.fetch("SLACK_TEAM_ID", "T0266FRGM")}/#{channel_id}"
  end
end

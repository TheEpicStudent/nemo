module ClusterHelper
  SERIES = 6
  SEPARATE_VERDICTS = %w[different_people].freeze

  TAB_PARTIALS = { "overview" => "overview", "accounts" => "accounts", "links" => "links",
                   "sessions" => "timeline", "snapshots" => "snapshots", "verdicts" => "verdicts" }.freeze
  ALERT_ICONS = {
    "alert" => ["M12 3 2 20h20L12 3Z", "M12 10v4", "M12 17v.01"],
    "scissors" => ["M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z", "M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z", "M20 4 8.1 15.9",
                   "M14.5 14.5 20 20", "M8.1 8.1 12 12"]
  }.freeze
  TIMELINE_WIDTH = 1000
  TIMELINE_SIDE = 12
  TIMELINE_TOP = 10
  TIMELINE_BOTTOM = 26
  TIMELINE_STACK = 150
  TIMELINE_BINS_MAX = 160
  TIMELINE_DOT_MIN = 2.2
  TIMELINE_DOT_MAX = 7

  MINI_WIDTH = 320
  MINI_HEIGHT = 150
  MINI_CROWDED = 12
  MINI_BEND = 0.08

  def cluster_mini_points(user_ids)
    count = user_ids.size
    cx = MINI_WIDTH / 2.0
    cy = MINI_HEIGHT / 2.0
    return { user_ids.first => [cx, cy] } if count == 1

    crowded = count > MINI_CROWDED
    rx = crowded ? [cx - 20, cy - 14].min : cx - 60
    ry = crowded ? rx : cy - 32
    return { user_ids[0] => [cx - (rx * 0.55), cy], user_ids[1] => [cx + (rx * 0.55), cy] } if count == 2

    user_ids.each_with_index.to_h do |user_id, index|
      angle = (-Math::PI / 2) + (2 * Math::PI * index / count)
      [user_id, [cx + (Math.cos(angle) * rx), cy + (Math.sin(angle) * ry)]]
    end
  end

  def cluster_mini_map(card)
    points = cluster_mini_points(card.members.map(&:user_id))
    crowded = card.members.size > MINI_CROWDED
    radius = crowded ? 4.5 : 8
    edges = card.edges.filter_map do |edge|
      a = points[edge.a_user_id]
      b = points[edge.b_user_id]
      next if a.nil? || b.nil?

      bend = crowded ? 0 : MINI_BEND
      qx = ((a[0] + b[0]) / 2) + (((MINI_WIDTH / 2.0) - ((a[0] + b[0]) / 2)) * bend)
      qy = ((a[1] + b[1]) / 2) + (((MINI_HEIGHT / 2.0) - ((a[1] + b[1]) / 2)) * bend)
      tag.path(class: cluster_edge_class(edge),
        d: format("M%<ax>.1f %<ay>.1f Q%<qx>.1f %<qy>.1f %<bx>.1f %<by>.1f", ax: a[0], ay: a[1], qx: qx, qy: qy,
          bx: b[0], by: b[1]))
    end
    nodes = card.members.map do |member|
      x, y = points[member.user_id]
      tag.circle(cx: x.round(1), cy: y.round(1), r: radius,
        class: ["mini-node", ("is-gone" if member.deactivated), ("is-oldest" if member.user_id == card.cluster_id)].compact.join(" "))
    end
    tag.svg(safe_join(edges + nodes), viewBox: "0 0 #{MINI_WIDTH} #{MINI_HEIGHT}",
      class: ["ccard-map", ("is-crowded" if crowded)].compact.join(" "), role: "img",
      aria: { label: "Link graph, #{card.accounts} accounts" })
  end

  def cluster_tab_count(cluster, key)
    case key
    when "accounts" then cluster.members.size
    when "links" then cluster.links.size
    when "snapshots" then cluster.snapshots.size
    when "verdicts" then cluster.verdict_edges.size
    end
  end

  def cluster_alert_icon(name)
    tag.svg(width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2,
      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": true) do
      safe_join(ALERT_ICONS.fetch(name).map { |path| tag.path(d: path) })
    end
  end

  def cluster_join_timeline(cluster)
    members = cluster.members.select(&:joined_at)
    return nil if members.empty?

    from = members.map(&:joined_at).min.beginning_of_day
    upto = Time.current
    span = timeline_span(upto - from)
    bins = ((upto - from) / span).ceil.clamp(1, TIMELINE_BINS_MAX)
    columns = members.group_by { |member| (((member.joined_at - from) / span).floor).clamp(0, bins - 1) }
    tallest = columns.values.map(&:size).max
    column_width = (TIMELINE_WIDTH - (2 * TIMELINE_SIDE)).to_f / bins
    radius = [column_width / 2.4, TIMELINE_STACK / (2.2 * tallest), TIMELINE_DOT_MAX].min.clamp(TIMELINE_DOT_MIN, TIMELINE_DOT_MAX)
    height = (TIMELINE_TOP + (tallest * radius * 2.2) + TIMELINE_BOTTOM).ceil
    base = height - TIMELINE_BOTTOM
    dots = columns.flat_map do |column, column_members|
      x = TIMELINE_SIDE + ((column + 0.5) * column_width)
      column_members.sort_by(&:joined_at).each_with_index.map do |member, index|
        timeline_dot(cluster, member, x, base - radius - (index * radius * 2.2), radius)
      end
    end
    axis = tag.line(x1: TIMELINE_SIDE, x2: TIMELINE_WIDTH - TIMELINE_SIDE, y1: base + 2, y2: base + 2, class: "timeline-axis")
    middle = from + ((upto - from) / 2)
    ticks = [[TIMELINE_SIDE, "start", on_day(from)], [TIMELINE_WIDTH / 2, "middle", on_day(middle)],
             [TIMELINE_WIDTH - TIMELINE_SIDE, "end", "now"]].map do |x, anchor, text|
      tag.text(text, x: x, y: height - 6, "text-anchor": anchor, class: "timeline-tick")
    end
    tag.svg(safe_join(dots + [axis] + ticks), viewBox: "0 0 #{TIMELINE_WIDTH} #{height}", role: "img",
      aria: { label: "When each account joined, one dot per account" })
  end

  def timeline_span(seconds)
    return 1.day if seconds <= 120.days
    return 1.week if seconds <= 2.years

    30.days
  end

  def timeline_dot(cluster, member, x, y, radius)
    ended = cluster.snapshot_of(member.user_id)&.deactivated_at if member.deactivated
    title = "#{person_label(member.user_id)}, joined #{on_day(member.joined_at)}" \
            "#{member.deactivated ? ", deactivated#{" #{on_day(ended)}" if ended}" : ""}"
    tag.a(href: fd_member_path(member.user_id), class: "timeline-dot-link") do
      tag.circle(tag.title(title), cx: x.round(1), cy: y.round(1), r: radius.round(1),
        class: ["timeline-dot", (member.deactivated ? "is-gone" : "is-active"),
                ("is-oldest" if member.user_id == cluster.cluster_id)].compact.join(" "))
    end
  end

  def cluster_flags(ring:, conflict:, returns:, all_gone:)
    flags = []
    flags << tag.span(safe_join([tag.i, "Ring"]), class: "flagx warn") if ring
    flags << tag.span(safe_join([tag.i, "Verdict conflict"]), class: "flagx crit") if conflict
    flags << tag.span(safe_join([tag.i, pluralize(returns, "post-ban join")]), class: "flagx crit") if returns.to_i.positive?
    flags << tag.span(safe_join([tag.i, "All deactivated"]), class: "flagx") if all_gone
    safe_join(flags)
  end

  def cluster_edge_class(edge)
    ["edge", "edge-#{edge_band(edge.score)}", edge_tone(edge.verdict)].compact.join(" ")
  end

  def edge_band(score)
    return "verdict" if score.nil?
    return "certain" if score >= Fd::MemberLink::CERTAIN
    return "strong" if score >= Fd::MemberLink::STRONG

    "weak"
  end

  def edge_tone(verdict)
    return nil if verdict.blank?

    SEPARATE_VERDICTS.include?(verdict) ? "edge-apart" : "edge-together"
  end

  def cluster_edge_title(edge)
    parts = [person_label(edge.a_user_id), person_label(edge.b_user_id)].join(" and ")
    score_label = edge.score ? number_with_precision(edge.score, precision: 1) : nil
    verdict = edge.verdict&.tr("_", " ")
    [parts, score_label, verdict].compact.join(", ")
  end

  def person_label(user_id)
    names[user_id].to_s.presence || user_id
  end

  def cluster_days(cluster)
    (cluster.since.to_date..Time.current.to_date).to_a
  end

  def cluster_sightings(cluster)
    @cluster_sightings ||= cluster.sightings.group_by { |sighting| [sighting.user_id, sighting.hour.to_date] }
  end

  def shared_tone(cluster, ip)
    position = cluster.shared_ips.index(ip)
    position && "var(--series-#{position % SERIES})"
  end

  def cluster_cell(cluster, user_id, day)
    sightings = cluster_sightings(cluster)[[user_id, day]] || []
    return tag.i(class: "none") if sightings.empty?

    shared = sightings.map(&:ip).find { |ip| cluster.shared_ips.include?(ip) }
    rows = sightings.group_by(&:ip).map do |ip, hours|
      { label: ip, value: hours.map { |sighting| sighting.hour.strftime("%H:00") }.uniq.join(", "),
        tone: shared_tone(cluster, ip) || "var(--muted-foreground)" }
    end
    tip = { title: "#{person_label(user_id)}, #{day.strftime('%-d %b')}", rows: rows }.to_json
    tag.i(class: shared ? "shared" : "own", style: ("background: #{shared_tone(cluster, shared)}" if shared),
      tabindex: 0, role: "img", data: { tip: tip }, aria: { label: "#{day.strftime('%-d %b')}, seen" })
  end
end

module ClusterHelper
  MAP_RADIUS = 140
  NODE_RADIUS = 18
  LABEL_GAP = 34
  MARGIN = 60
  CROWDED = 16
  PACKED = 30
  NODE_GAP = 10
  SPOKE_GAP = 6
  SPOKE_ROOM = 125
  PULL = 0.2
  DISC = 60
  DISC_NODE = 12
  DISC_GAP = 5
  DISC_MARGIN = 24
  GOLDEN = Math::PI * (3 - Math.sqrt(5))
  SERIES = 6
  SEPARATE_VERDICTS = %w[different_people household].freeze

  TAB_PARTIALS = { "overview" => "overview", "accounts" => "accounts", "links" => "links",
                   "sessions" => "timeline", "snapshots" => "snapshots", "verdicts" => "verdicts" }.freeze
  ALERT_ICONS = {
    "alert" => ["M12 3 2 20h20L12 3Z", "M12 10v4", "M12 17v.01"],
    "scissors" => ["M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z", "M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z", "M20 4 8.1 15.9",
                   "M14.5 14.5 20 20", "M8.1 8.1 12 12"]
  }.freeze
  TIMELINE_ROWS = 60
  TIMELINE_LEFT = 170
  TIMELINE_WIDTH = 1000

  MapLayout = Struct.new(:size, :centre, :node, :crowded, :packed, :pull, :points, keyword_init: true)

  def cluster_layout(cluster)
    count = [cluster.members.size, 1].max
    return disc_layout(cluster, count) if count > DISC

    crowded = count > CROWDED
    node = node_radius(count)
    radius = [MAP_RADIUS, count * ((2 * node) + NODE_GAP) / (2 * Math::PI)].max
    half = crowded ? radius + node + SPOKE_GAP + SPOKE_ROOM : radius + MARGIN
    points = cluster.members.each_with_index.to_h do |member, index|
      angle = (-Math::PI / 2) + (2 * Math::PI * index / count)
      [member.user_id, map_point(angle, radius, half, node, crowded).merge(step: index)]
    end
    MapLayout.new(size: (2 * half).round, centre: half, node: node, crowded: crowded, packed: false,
      pull: PULL, points: points)
  end

  def disc_layout(cluster, count)
    step = ((2 * DISC_NODE) + DISC_GAP) / Math.sqrt(Math::PI)
    half = (step * Math.sqrt(count)) + DISC_NODE + DISC_MARGIN
    points = cluster.members.each_with_index.to_h do |member, index|
      distance = step * Math.sqrt(index + 0.5)
      x = half + (distance * Math.cos(index * GOLDEN))
      y = half + (distance * Math.sin(index * GOLDEN))
      [member.user_id, { x: x, y: y, lx: x, ly: y - DISC_NODE - 6, anchor: "middle", turn: 0, step: index }]
    end
    MapLayout.new(size: (2 * half).round, centre: half, node: DISC_NODE, crowded: true, packed: true,
      pull: 1.0, points: points)
  end

  def node_radius(count)
    return 11 if count > PACKED
    return 14 if count > CROWDED

    NODE_RADIUS
  end

  def map_point(angle, radius, half, node, crowded)
    cos = Math.cos(angle)
    sin = Math.sin(angle)
    point = { x: half + (radius * cos), y: half + (radius * sin) }
    return point.merge(lx: half + ((radius + LABEL_GAP) * cos), ly: half + ((radius + LABEL_GAP) * sin),
      anchor: label_anchor(cos), turn: 0) unless crowded

    label_radius = radius + node + SPOKE_GAP
    degrees = angle * 180 / Math::PI
    point.merge(lx: half + (label_radius * cos), ly: half + (label_radius * sin),
      anchor: cos.negative? ? "end" : "start", turn: cos.negative? ? degrees + 180 : degrees)
  end

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
    members = cluster.members.select(&:joined_at).first(TIMELINE_ROWS)
    return nil if members.empty?

    from = members.map(&:joined_at).min
    upto = Time.current
    row_height = members.size > 12 ? 14 : 24
    x = ->(time) { TIMELINE_LEFT + ((time - from) / [upto - from, 1].max * (TIMELINE_WIDTH - TIMELINE_LEFT - 20)) }
    rows = members.each_with_index.map do |member, index|
      y = 20 + (index * row_height)
      ended = cluster.snapshot_of(member.user_id)&.deactivated_at if member.deactivated
      finish = [x.call(ended || upto), x.call(member.joined_at) + 2].max
      title = "#{person_label(member.user_id)}, joined #{on_day(member.joined_at)}#{", deactivated #{on_day(ended)}" if ended}"
      safe_join([
        tag.text(person_label(member.user_id).to_s.truncate(22), x: 0, y: y + 4, class: "timeline-name"),
        tag.line(tag.title(title), x1: x.call(member.joined_at).round(1), x2: finish.round(1), y1: y, y2: y,
          class: ["timeline-bar", (member.deactivated ? "is-gone" : "is-active")].join(" "),
          "stroke-width": row_height < 20 ? 4 : 6)
      ])
    end
    height = 20 + (members.size * row_height) + 24
    ticks = [[from, "start", on_day(from)], [from + ((upto - from) / 2), "middle", on_day(from + ((upto - from) / 2))],
             [upto, "end", "now"]].map do |at, anchor, text|
      tag.text(text, x: x.call(at).round(1), y: height - 4, "text-anchor": anchor, class: "timeline-tick")
    end
    tag.svg(safe_join(rows + ticks), viewBox: "0 0 #{TIMELINE_WIDTH} #{height}", role: "img",
      aria: { label: "Join and deactivation timeline" })
  end

  def cluster_flags(ring:, conflict:, returns:, all_gone:)
    flags = []
    flags << tag.span(safe_join([tag.i, "Ring"]), class: "flagx warn") if ring
    flags << tag.span(safe_join([tag.i, "Verdict conflict"]), class: "flagx crit") if conflict
    flags << tag.span(safe_join([tag.i, pluralize(returns, "post-ban join")]), class: "flagx crit") if returns.to_i.positive?
    flags << tag.span(safe_join([tag.i, "All deactivated"]), class: "flagx") if all_gone
    safe_join(flags)
  end

  def cluster_edge_path(layout, a, b)
    centre = layout.centre
    cx = centre + ((((a[:x] + b[:x]) / 2) - centre) * layout.pull)
    cy = centre + ((((a[:y] + b[:y]) / 2) - centre) * layout.pull)
    format("M%<ax>.1f %<ay>.1f Q%<cx>.1f %<cy>.1f %<bx>.1f %<by>.1f",
      ax: a[:x], ay: a[:y], cx: cx, cy: cy, bx: b[:x], by: b[:y])
  end

  def label_anchor(cos)
    return "middle" if cos.abs < 0.3

    cos.positive? ? "start" : "end"
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

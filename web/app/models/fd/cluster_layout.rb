module Fd
  class ClusterLayout
    LABELED = 24
    NODE_RADII = [[LABELED, 18], [60, 14]].freeze
    PACKED_NODE = 11
    NODE_GAP = 12
    RING_MIN = 92
    LABEL_CLEARANCE = 44
    HOVER_CLEARANCE = 10
    GROUP_GAP = 28
    MARGIN = 24
    EDGE_CURVE = 0.35
    PAIR_WIDTH = 360
    PAIR_HEIGHT = 150
    PAIR_SPAN = 150
    PASSES = 20
    ASPECT = 2.4

    Point = Struct.new(:x, :y, :lx, :ly, :anchor, :step, :group, :hub, :labeled, keyword_init: true)
    Group = Struct.new(:index, :hub, :others, :x, :y, :ring, :reach, keyword_init: true) do
      def size = others.size + (hub ? 1 : 0)
    end

    attr_reader :width, :height, :node, :points, :groups

    def initialize(cluster)
      @cluster = cluster
      @ids = cluster.members.map(&:user_id)
      @order = @ids.each_with_index.to_h
      @node = node_radius
      build
    end

    def packed? = @ids.size > LABELED

    def size = [@width, @height].max

    def edge_path(a_id, b_id)
      a = points[a_id]
      b = points[b_id]
      return nil if a.nil? || b.nil?

      straight = a.group != b.group || a.hub || b.hub
      return format("M%<ax>.1f %<ay>.1f L%<bx>.1f %<by>.1f", ax: a.x, ay: a.y, bx: b.x, by: b.y) if straight

      centre = groups[a.group]
      cx = centre.x + ((((a.x + b.x) / 2) - centre.x) * EDGE_CURVE)
      cy = centre.y + ((((a.y + b.y) / 2) - centre.y) * EDGE_CURVE)
      format("M%<ax>.1f %<ay>.1f Q%<cx>.1f %<cy>.1f %<bx>.1f %<by>.1f",
        ax: a.x, ay: a.y, cx: cx, cy: cy, bx: b.x, by: b.y)
    end

    private

    def node_radius
      NODE_RADII.each { |limit, radius| return radius if @ids.size <= limit }
      PACKED_NODE
    end

    def build
      return pair if @ids.size <= 2

      linked, loose = grouped.partition { |members| members.size > 1 }
      sets = loose.size > 1 ? linked + [loose.flatten] : linked + loose
      @groups = sets.each_with_index.map { |members, index| shape(members, index, loose: loose.size > 1 && members == loose.flatten) }
      position_groups
      @points = {}
      groups.each { |group| point_group(group) }
      fit
    end

    def pair
      @groups = [Group.new(index: 0, hub: @ids.first, others: @ids.drop(1), x: PAIR_WIDTH / 2.0, y: PAIR_HEIGHT / 2.0)]
      @width = PAIR_WIDTH
      @height = PAIR_HEIGHT
      xs = @ids.one? ? [PAIR_WIDTH / 2.0] : [(PAIR_WIDTH - PAIR_SPAN) / 2.0, (PAIR_WIDTH + PAIR_SPAN) / 2.0]
      @points = @ids.each_with_index.to_h do |user_id, index|
        y = (PAIR_HEIGHT / 2.0) - 12
        [user_id, Point.new(x: xs[index], y: y, lx: xs[index], ly: y + @node + 16, anchor: "middle", step: index,
          group: 0, hub: index.zero?, labeled: true)]
      end
    end

    def grouped
      labels = @ids.to_h { |user_id| [user_id, user_id] }
      PASSES.times do
        changed = false
        @ids.each do |user_id|
          best = strongest_label(user_id, labels)
          next if best.nil? || best == labels[user_id]

          labels[user_id] = best
          changed = true
        end
        break unless changed
      end
      attach_isolated(labels)
      labels.group_by { |_user_id, label| label }.values.map { |pairs| pairs.map(&:first) }
        .sort_by { |members| [-members.size, members.map { |user_id| @order[user_id] }.min] }
    end

    def strongest_label(user_id, labels)
      weights = Hash.new(0.0)
      strong_neighbours[user_id].each { |other, weight| weights[labels[other]] += weight }
      return nil if weights.empty?

      weights.max_by { |label, weight| [weight, -@order[label]] }.first
    end

    def attach_isolated(labels)
      counts = labels.values.tally
      @ids.each do |user_id|
        next unless counts[labels[user_id]] == 1

        other = any_neighbours[user_id].max_by { |neighbour, weight| [weight, -@order[neighbour]] }&.first
        labels[user_id] = labels[other] if other
      end
    end

    def strong_neighbours
      @strong_neighbours ||= neighbours { |edge| edge.score.nil? ? together?(edge) : edge.score >= MemberLink::STRONG }
    end

    def any_neighbours
      @any_neighbours ||= neighbours { |edge| edge.score || together?(edge) }
    end

    def together?(edge) = edge.verdict.present? && !edge.apart?

    def neighbours
      table = @ids.to_h { |user_id| [user_id, Hash.new(0.0)] }
      @cluster.edges.each do |edge|
        next if edge.apart? || !table.key?(edge.a_user_id) || !table.key?(edge.b_user_id)
        next unless yield(edge)

        weight = edge.score || MemberLink::CERTAIN
        table[edge.a_user_id][edge.b_user_id] += weight
        table[edge.b_user_id][edge.a_user_id] += weight
      end
      table
    end

    def shape(members, index, loose: false)
      hub = loose ? nil : hub_of(members)
      others = (members - [hub]).sort_by { |user_id| @order[user_id] }
      ring = others.empty? ? 0 : [RING_MIN, others.size * ((2 * node) + NODE_GAP) / (2 * Math::PI)].max
      clearance = packed? ? HOVER_CLEARANCE : LABEL_CLEARANCE
      Group.new(index: index, hub: hub, others: others, ring: ring, reach: ring + node + clearance)
    end

    def hub_of(members)
      members.max_by do |user_id|
        within = strong_neighbours[user_id].sum { |other, weight| members.include?(other) ? weight : 0 }
        [within, -@order[user_id]]
      end
    end

    def position_groups
      rows = group_rows
      widths = rows.map { |row| row.sum { |group| 2 * group.reach } + (GROUP_GAP * (row.size - 1)) }
      widest = widths.max
      top = 0.0
      rows.each_with_index do |row, index|
        height = row.map { |group| 2 * group.reach }.max
        left = (widest - widths[index]) / 2
        row.each do |group|
          group.x = left + group.reach
          group.y = top + (height / 2)
          left += (2 * group.reach) + GROUP_GAP
        end
        top += height + GROUP_GAP
      end
    end

    def group_rows
      target = [groups.map { |group| 2 * group.reach }.max,
                Math.sqrt(groups.sum { |group| (2 * group.reach)**2 } * ASPECT)].max
      groups.each_with_object([[]]) do |group, rows|
        used = rows.last.sum { |row_group| (2 * row_group.reach) + GROUP_GAP }
        rows << [] if rows.last.any? && used + (2 * group.reach) > target + GROUP_GAP
        rows.last << group
      end
    end

    def point_group(group)
      labeled_others = !packed?
      if group.hub
        @points[group.hub] = Point.new(x: group.x, y: group.y, lx: group.x, ly: group.y - node - 8, anchor: "middle",
          step: @order[group.hub], group: group.index, hub: true, labeled: true)
      end
      group.others.each_with_index do |user_id, index|
        angle = (-Math::PI / 2) + (2 * Math::PI * index / group.others.size)
        cos = Math.cos(angle)
        sin = Math.sin(angle)
        label_at = group.ring + node + 8
        @points[user_id] = Point.new(x: group.x + (group.ring * cos), y: group.y + (group.ring * sin),
          lx: group.x + (label_at * cos), ly: group.y + (label_at * sin), anchor: anchor_for(cos),
          step: @order[user_id], group: group.index, hub: false, labeled: labeled_others)
      end
    end

    def anchor_for(cos)
      return "middle" if cos.abs < 0.3

      cos.positive? ? "start" : "end"
    end

    def fit
      left = groups.map { |group| group.x - group.reach }.min - MARGIN
      top = groups.map { |group| group.y - group.reach }.min - MARGIN
      right = groups.map { |group| group.x + group.reach }.max + MARGIN
      bottom = groups.map { |group| group.y + group.reach }.max + MARGIN
      groups.each do |group|
        group.x -= left
        group.y -= top
      end
      @points.each_value do |point|
        point.x -= left
        point.y -= top
        point.lx -= left
        point.ly -= top
      end
      @width = (right - left).round
      @height = (bottom - top).round
    end
  end
end

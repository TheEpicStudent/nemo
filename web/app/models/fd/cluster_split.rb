module Fd
  class ClusterSplit
    EDGE_SCORE = MemberLink::SIGNALS.dig("clusters", "edge_score")
    UNCLUSTERED_LABELS = %w[household classroom].freeze
    TOGETHER = LinkVerdict::ONE_PERSON
    BOUND = Float::INFINITY

    Cut = Struct.new(:a_user_id, :b_user_id, :score, keyword_init: true)

    def initialize(cluster)
      @cluster = cluster
    end

    def pairs = @cluster.conflicts.map { |edge| [edge.a_user_id, edge.b_user_id] }

    def cuts
      @cuts ||= begin
        graph = capacities
        pairs.flat_map do |source, sink|
          cut = minimum_cut(graph, source, sink)
          cut.each { |a, b| graph[a].delete(b) && graph[b].delete(a) }
          cut
        end.uniq.map { |a, b| build_cut(a, b) }
      end
    end

    def possible? = cuts.any?

    private

    def clustering?(edge)
      return TOGETHER.include?(edge.verdict) if edge.score.nil?
      return false if edge.apart?
      return true if TOGETHER.include?(edge.verdict)

      edge.score >= EDGE_SCORE && !UNCLUSTERED_LABELS.include?(edge.label)
    end

    def capacities
      @cluster.edges.select { |edge| clustering?(edge) }.each_with_object(Hash.new { |hash, key| hash[key] = {} }) do |edge, graph|
        capacity = TOGETHER.include?(edge.verdict) ? BOUND : edge.score
        graph[edge.a_user_id][edge.b_user_id] = capacity
        graph[edge.b_user_id][edge.a_user_id] = capacity
      end
    end

    def minimum_cut(graph, source, sink)
      return [] unless graph.key?(source) && graph.key?(sink)

      residual = graph.transform_values(&:dup)
      residual.default_proc = proc { |hash, key| hash[key] = {} }
      while (path = augmenting_path(residual, source, sink))
        flow = path.each_cons(2).map { |a, b| residual[a][b] }.min
        break if flow == BOUND

        path.each_cons(2) do |a, b|
          residual[a][b] -= flow
          residual[b][a] = residual[b].fetch(a, 0) + flow
        end
      end
      reachable = reachable_from(residual, source)
      return [] if reachable.include?(sink)

      reachable.flat_map do |a|
        graph[a].keys.reject { |b| reachable.include?(b) }.map { |b| [a, b].minmax }
      end
    end

    def augmenting_path(residual, source, sink)
      previous = { source => nil }
      queue = [source]
      until queue.empty?
        current = queue.shift
        residual[current].each do |neighbour, capacity|
          next if capacity <= 0 || previous.key?(neighbour)

          previous[neighbour] = current
          return walk_back(previous, sink) if neighbour == sink

          queue << neighbour
        end
      end
      nil
    end

    def walk_back(previous, sink)
      path = [sink]
      path.unshift(previous[path.first]) while previous[path.first]
      path
    end

    def reachable_from(residual, source)
      seen = Set[source]
      queue = [source]
      until queue.empty?
        residual[queue.shift].each do |neighbour, capacity|
          next if capacity <= 0 || seen.include?(neighbour)

          seen << neighbour
          queue << neighbour
        end
      end
      seen
    end

    def build_cut(a, b)
      edge = @cluster.edges.find { |one| one.a_user_id == a && one.b_user_id == b }
      Cut.new(a_user_id: a, b_user_id: b, score: TOGETHER.include?(edge&.verdict) ? nil : edge&.score)
    end
  end
end

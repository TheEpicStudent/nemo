module Fd
  class MemberLinksController < BaseController
    permit "member.links"

    LIMIT = 100
    VIEWS = { "review" => "Needs review", "clusters" => "Clusters", "pairs" => "All pairs" }.freeze
    DEFAULT_VIEW = "review".freeze

    def index
      @view = VIEWS.keys.find { |key| key == params[:view] } || DEFAULT_VIEW
      ids = case @view
      when "clusters" then clusters_ids
      when "pairs" then pairs_ids
      else review_ids
      end
      @names = Names.for(ids + @verdicts.values.map(&:decided_by))
      @health = LinkHealth.load
    end

    private

    def review_ids
      @pairs = MemberLink.needs_review(limit: LIMIT)
      @verdicts = {}
      @pairs.flat_map { |pair| [pair.active_id, pair.deactivated_id] }
    end

    def clusters_ids
      @clusters = MemberLink.clusters(limit: LIMIT)
      @verdicts = {}
      @clusters.map(&:cluster_id)
    end

    def pairs_ids
      @links = MemberLink.strongest(limit: LIMIT, over: score_floor)
      @verdicts = LinkVerdict.for_pairs(@links.map { |link| [link.a_user_id, link.b_user_id] })
      @links.flat_map { |link| [link.a_user_id, link.b_user_id] }
    end

    def score_floor
      requested = params[:over].to_s
      return MemberLink::CERTAIN if requested == "certain"
      return MemberLink::STRONG if requested == "strong"

      nil
    end
  end
end

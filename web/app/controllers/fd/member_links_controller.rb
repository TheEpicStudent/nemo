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
      @pairs.flat_map { |one| [one.active_id, one.deactivated_id] }
    end

    def clusters_ids
      @clusters = MemberLink.clusters(limit: LIMIT)
      @verdicts = {}
      @clusters.map(&:cluster_id)
    end

    def pairs_ids
      @links = MemberLink.strongest(limit: LIMIT, over: over)
      @verdicts = LinkVerdict.for_pairs(@links.map { |one| [one.a_user_id, one.b_user_id] })
      @links.flat_map { |one| [one.a_user_id, one.b_user_id] }
    end

    def over
      asked = params[:over].to_s
      return MemberLink::CERTAIN if asked == "certain"
      return MemberLink::STRONG if asked == "strong"

      nil
    end
  end
end

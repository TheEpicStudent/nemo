module Fd
  class MemberLinksController < BaseController
    permit "member.links"

    OLD_PAIR_VIEWS = { "certain" => "certain", "strong" => "strong" }.freeze

    def index
      return redirect_to(fd_clusters_path) if params[:view] == "clusters"
      return redirect_to(fd_links_path(view: OLD_PAIR_VIEWS.fetch(params[:over].to_s, "certain"))) if params[:view] == "pairs"

      @list = LinkList.new(params)
      @names = Names.for(@list.user_ids + @list.rows.filter_map(&:decided_by))
      @health = LinkHealth.load
    end

    def compare
      @compare = LinkCompare.find(params[:a], params[:b], actor: current_account, variant: params[:variant])
      return head :not_found if @compare.nil?

      @compare.record_reads!
      @names = Names.for(@compare.user_ids_named)
      @channels = ChannelNames.for(@compare.channel_ids)
      @contexts = MemberContext.for(@compare.ids)
      @back = back_path
    end

    private

    def back_path
      requested_path = params[:back].to_s
      requested_path.start_with?("/fd/") ? requested_path : nil
    end
  end
end

module Fd
  class ClustersController < BaseController
    permit "member.links"

    TABS = { "overview" => "Overview", "accounts" => "Accounts", "links" => "Links", "sessions" => "Sessions",
             "snapshots" => "Snapshots", "verdicts" => "Verdicts" }.freeze
    IDENTITY_TABS = %w[sessions snapshots].freeze

    def index
      @list = ClusterList.new(params)
      @names = Names.for(@list.user_ids)
    end

    def show
      @cluster = ClusterView.find(params[:id])
      return head :not_found if @cluster.nil?

      @identity = current_account.may?("identity.read")
      @tabs = @identity ? TABS : TABS.except(*IDENTITY_TABS)
      @tab = @tabs.key?(params[:tab]) ? params[:tab] : "overview"
      AccessLog.record_many!(actor: current_account, subject_user_ids: @cluster.ids, field_class: "links")
      AccessLog.record_many!(actor: current_account, subject_user_ids: @cluster.ids, field_class: "login") if @identity
      @split = ClusterSplit.new(@cluster)
      @names = Names.for(@cluster.ids + @cluster.snapshots.filter_map(&:actor_id) +
                         @cluster.edges.filter_map(&:decided_by))
    end

    def node
      @cluster = ClusterView.find(params[:id])
      @user_id = params[:user_id].to_s.upcase
      return head :not_found if @cluster.nil? || @cluster.member(@user_id).nil?
      return redirect_to(fd_cluster_path(@cluster.cluster_id, node: @user_id)) unless turbo_frame_request?

      @traits = MemberTraits.new([@user_id], actor: current_account)
      AccessLog.record!(actor: current_account, subject_user_id: @user_id, field_class: "login") if @traits.identity?
      @names = Names.for([@user_id] + @cluster.links_of(@user_id).map { |edge| edge.other(@user_id) } +
                         [@cluster.snapshot_of(@user_id)&.actor_id].compact)
      render layout: false
    end
  end
end

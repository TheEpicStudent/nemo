module Fd
  class ClusterSplitsController < BaseController
    permit "link.verdict"

    def create
      cluster = ClusterView.find(params[:cluster_id])
      return head :not_found if cluster.nil?

      split = ClusterSplit.new(cluster)
      return redirect_to(fd_cluster_path(cluster.cluster_id), alert: "nothing to split") unless split.possible?

      note = "Split cluster #{cluster.cluster_id}"
      writing { split.cuts.each { |cut| record(cut, note) } }
      redirect_to fd_cluster_path(cluster.cluster_id),
        notice: "#{split.cuts.size} #{'link'.pluralize(split.cuts.size)} marked different people"
    end

    private

    def record(cut, note)
      existing = LinkVerdict.lock.find_by(a_user_id: cut.a_user_id, b_user_id: cut.b_user_id)
      before = existing&.audit_attributes
      row = existing || LinkVerdict.new(a_user_id: cut.a_user_id, b_user_id: cut.b_user_id)
      row.update!(verdict: "different_people", decided_by: current_account.user_id, decided_at: Time.current, note: note)
      audit(row, row.verb, before: before,
        after: row.audit_attributes.merge("a_user_id" => cut.a_user_id, "b_user_id" => cut.b_user_id),
        subject_user_id: cut.b_user_id)
    end
  end
end

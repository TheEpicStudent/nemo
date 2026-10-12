module Fd
  class MemberLinkPanesController < BaseController
    permit "member.links"

    def show
      user_id = params[:member_id].to_s.upcase
      links = MemberLink.for_member(user_id)
      cluster_members = MemberLink.cluster_members(user_id, except: links.map(&:other_id))
      verdicts = LinkVerdict.for_pairs(links.map { |link| [user_id, link.other_id] })
      visible_member_ids = cluster_members.keys.first(MemberLink::CLUSTER_MEMBER_LIMIT)
      names = Names.for([user_id] + links.map(&:other_id) + visible_member_ids + verdicts.values.map(&:decided_by))
      @names = names

      AccessLog.record!(actor: current_account, subject_user_id: user_id,
        field_class: "links")

      render partial: "fd/members/links", layout: false,
        locals: { user_id: user_id, links: links, cluster_members: cluster_members, names: names,
                  verdicts: verdicts, cluster_of: MemberLink.cluster_of(user_id) }
    end
  end
end

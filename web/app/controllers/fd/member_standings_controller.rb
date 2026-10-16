module Fd
  class MemberStandingsController < BaseController
    permit "case.read"

    def show
      user_id = params[:member_id].to_s.upcase
      guards = MemberGuard.by_severity(MemberGuard.standing_on(user_id))

      render partial: "fd/members/standing", layout: false, locals: {
        user_id: user_id, guards: guards, names: Names.for(referenced_user_ids(guards) + [user_id]),
        may_guard: current_account.may?("member.guard"),
        may_deactivate: current_account.may?("member.deactivate")
      }
    end

    private

    def referenced_user_ids(guards)
      guards.flat_map(&:referenced_user_ids) + guards.map(&:subject_id)
    end
  end
end

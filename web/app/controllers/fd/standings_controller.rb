module Fd
  class StandingsController < BaseController
    permit "case.read"

    def show
      kase = Case.find(params[:case_id])
      guards = MemberGuard.standing_on(params[:target_user_id])
      @channels = ChannelNames.for(guards.map(&:channel_id))

      render partial: "fd/cases/standing", layout: false,
        locals: { guards: guards, kase: kase, names: Names.for(referenced_user_ids(guards)),
                  logged: Action.guards_logged_on(kase.family_ids) }
    end

    private

    def referenced_user_ids(guards)
      guards.flat_map(&:referenced_user_ids) + guards.map(&:subject_id)
    end
  end
end

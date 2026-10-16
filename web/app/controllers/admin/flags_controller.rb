module Admin
  class FlagsController < BaseController
    ROUTES = {
      "fire_engine" => [["/fd/cases", :path], ["/fd/members", :path],
                        ["Search palette", :note]],
      "analytics" => [["/", :path], ["/channels", :path], ["/engine", :path]]
    }.freeze

    def show
      @flags = Fd::Flag::LISTED.sort_by { |key| Fd::Flag.on?(key) ? 1 : 0 }
      @disabled_flags = Fd::Flag::LISTED.reject { |key| Fd::Flag.on?(key) }
      @holder_counts = Fd::Flag::LISTED.index_with { |key| holder_count(key) }
      @flag_rows = Fd::Flag.where(key: Fd::Flag::LISTED).index_by(&:key)
      @names = Fd::Names.for(@flag_rows.values.filter_map(&:changed_by))
    end

    private

    def holder_count(key)
      Authz.holders_of(fd?(key) ? "case.read" : "channel.read").size
    end

    def fd?(key)
      key.to_s == "fire_engine"
    end

    def routes(key)
      ROUTES.fetch(key.to_s, [])
    end
    helper_method :routes
  end
end

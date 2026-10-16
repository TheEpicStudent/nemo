module Admin
  class RolesController < BaseController
    def show
      @roles = Authz.role_names.reject { |role| Authz.superadmin?(role) }
      @keys = Authz.by_area
      @holders = holders
      @overrides = Authz::Override.all.index_by { |row| [row.role, row.capability] }
      @override_count = @overrides.size
    end

    private

    def holders
      rows = ApplicationRecord.connection.select_all(
        "SELECT role, count(*) AS holder_count FROM app.effective_role GROUP BY role"
      )
      rows.to_h { |row| [row["role"], row["holder_count"].to_i] }
    end
  end
end

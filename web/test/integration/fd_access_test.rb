require "test_helper"

class FdAccessTest < ActionDispatch::IntegrationTest
  setup do
    Rails.application.eager_load!
    @me = Account.create!(user_id: "UFF1")
    grant_role!("UFF1", "firefighter")
    sign_in_as(@me)
  end

  def self.fd_writes
    Rails.application.routes.routes.filter_map do |route|
      controller = route.defaults[:controller].to_s
      next unless controller.start_with?("fd/")

      verbs = route.verb.to_s.gsub(/[$^]/, "").split("|")
      next if (verbs - %w[GET HEAD]).empty?

      [controller, route.defaults[:action].to_s]
    end.uniq
  end

  def controller_for(name)
    "#{name}_controller".camelize.constantize
  end

  def refusals
    Fd::AuditEntry.where(verb: "refused", actor_user_id: @me.user_id)
  end

  EXEMPT_KEYS = %w[case.read].freeze

  BOT = Rails.root.join("..", "pipeline", "bot")

  def self.enforced_by_bot
    Dir["#{BOT}/**/*.py"].flat_map { |path|
      File.read(path).scan(/(?:needs=|may\(|declared\()[^)]*?"([\w.]+\.[\w.]+)"/).flatten
    }.uniq
  end

  def self.enforced
    controllers = Rails.application.routes.routes.filter_map { |route|
      route.defaults[:controller].to_s.presence
    }.uniq.select { |name| name.start_with?("fd/") }

    declared = controllers.flat_map { |name| "#{name}_controller".camelize.constantize.declared }
    code_keys = Dir["#{Rails.root}/app/**/*.{rb,erb}"].flat_map { |path|
      File.read(path)
        .scan(/(?:may\?|allow\?|why_not|holds\?|may_community\?)\(\s*(?:[\w.@]+,\s*)?"([\w.]+)"/)
        .flatten
    }
    checked_keys = code_keys + code_keys.filter_map { |key| Community::Access::CAPABILITY[key] }
    panel_keys = Panel.keys.filter_map { |key| Panel.needs(key) }
    (declared + checked_keys + panel_keys).uniq
  end

  test "every Authz key is checked in dashboard code or bot code" do
    unenforced = Authz.keys - self.class.enforced - self.class.enforced_by_bot - EXEMPT_KEYS

    assert_empty unenforced,
      "#{unenforced.join(', ')} not read by the dashboard or the bot"
  end

  test "fd write routes declare permission keys that exist in Authz.keys" do
    self.class.fd_writes.each do |name, action|
      keys = controller_for(name).declared
      assert keys.any?, "#{name}##{action} writes without declaring a permission"
      keys.each do |key|
        assert_includes Authz.keys, key, "#{name} names #{key}, which does not exist"
      end
    end
  end

  RULE_CHANGE_KEYS = %w[access.grant app.flip].freeze

  test "fd write routes declaring rule change keys are role_permissions and flags" do
    rule_change_routes = self.class.fd_writes.select do |name, _action|
      controller_for(name).declared.intersect?(RULE_CHANGE_KEYS)
    end.map(&:first).uniq

    assert_equal %w[fd/role_permissions fd/flags].sort,
      rule_change_routes.sort,
      "rule change routes differ from the expected controllers"
  end

  test "admin grants create as firefighter grants no role and redirects to root" do
    post admin_grants_path, params: { user_id: "U0NEW", role: "firefighter", reason: "why not" }

    assert_empty Authz.effective_roles("U0NEW")
    assert_redirected_to root_path
  end

  test "case reversals create as firefighter reverses action with no refusal" do
    kase = make_case(opened_at: 2.days.ago)
    action = Fd::Action.create!(case_id: kase.id, type_key: "warning", target_user_id: "USUB",
      decided_by: "UOTHER", performed_by: "UOTHER")

    post fd_case_reversals_path(kase), params: { action_id: action.id,
      reversal_reason: "they appealed" }

    assert_not_nil action.reload.reversed_at
    assert_equal 0, refusals.count
  end

  test "case reversals create as firefighter on case assigned to another user reverses action" do
    kase = make_case(opened_at: 2.days.ago)
    kase.assign!("UOTHER")
    action = Fd::Action.create!(case_id: kase.id, type_key: "warning", target_user_id: "USUB",
      decided_by: "UOTHER", performed_by: "UOTHER")

    post fd_case_reversals_path(kase), params: { action_id: action.id,
      reversal_reason: "they appealed" }

    assert_not_nil action.reload.reversed_at
    assert_equal 0, refusals.count
  end

  test "firefighter note then action then resolution creates rows with no refusal" do
    kase = make_case(opened_at: 2.days.ago)

    post fd_case_notes_path(kase), params: { body: "asked them to stop" }
    assert_equal 1, kase.notes.count

    post fd_case_actions_path(kase), params: { type_key: "warning", target_user_id: "USUB",
                                               reason: "warned for the same thing twice" }
    assert_equal 1, kase.actions.count

    post fd_case_resolution_path(kase), params: { outcome: "close", close_reason: "no_action" }
    assert_not_nil kase.reload.resolved_at

    assert_equal 0, refusals.count
  end

  test "case notes create by account without grants creates no note" do
    delete logout_path
    account_without_grants = Account.create!(user_id: "USTRANGER")
    sign_in_as(account_without_grants)
    kase = make_case(opened_at: 2.days.ago)

    post fd_case_notes_path(kase), params: { body: "hello" }

    assert_equal 0, kase.notes.count
    assert_empty Authz.effective_roles(account_without_grants.user_id)
  end

  test "firefighter has case.reverse without access.grant and manager has access.grant" do
    firefighter_account = Account.create!(user_id: "ULEAD")
    grant_role!("ULEAD", "firefighter")

    assert firefighter_account.may?("case.reverse")
    assert_not firefighter_account.may?("access.grant")

    manager = grant_role!("UBOSS", "community_manager")
    assert manager.may?("access.grant")
  end
end

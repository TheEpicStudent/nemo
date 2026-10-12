require "test_helper"

class PrometheusMirrorTest < ActiveSupport::TestCase
  WHO = "UPROM0001".freeze
  UNREACHABLE_URL = "http://127.0.0.1:9".freeze

  setup do
    ENV["PROMETHEUS_BASE_URL"] = "http://prometheus.test"
    Account.find_or_create_by!(user_id: WHO)
    Prometheus::Appointment.delete_all
    Rails.cache.delete("prometheus/checked/#{WHO}")
    Current.forget_roles
  end

  teardown do
    ENV.delete("PROMETHEUS_BASE_URL")
    Prometheus::Appointment.delete_all
    Current.forget_roles
  end

  def stub_roster(name, result)
    original = Prometheus::Roster.method(name)
    Prometheus::Roster.define_singleton_method(name) { |*| result.respond_to?(:call) ? result.call : result }
    yield
  ensure
    Prometheus::Roster.define_singleton_method(name, original)
  end

  def appointments(user_id = WHO)
    Prometheus::Appointment.for_person(user_id).order(:channel_id).pluck(:channel_id, :role)
  end

  def settle_appointments(*channels)
    Prometheus::Mirror.replace_appointments(WHO, channels)
  end

  test "settling writes what Prometheus holds" do
    settle_appointments({ "channel_id" => "C1", "role" => "manager" },
      { "channel_id" => "C2", "role" => "moderator" })

    assert_equal [["C1", "manager"], ["C2", "moderator"]], appointments
  end

  test "only a manager appointment carries the role" do
    settle_appointments({ "channel_id" => "C1", "role" => "moderator" })
    assert_empty Authz.effective_roles(WHO)

    settle_appointments({ "channel_id" => "C1", "role" => "manager" })
    assert_equal ["promethean"], Authz.effective_roles(WHO)
  end

  test "a shrunk answer takes channels away" do
    settle_appointments({ "channel_id" => "C1", "role" => "manager" },
      { "channel_id" => "C2", "role" => "manager" })
    settle_appointments({ "channel_id" => "C1", "role" => "manager" })

    assert_equal [["C1", "manager"]], appointments
  end

  test "an unknown role or a blank channel is dropped rather than written" do
    settle_appointments({ "channel_id" => "C1", "role" => "owner" },
      { "channel_id" => "", "role" => "manager" },
      { "channel_id" => "C2", "role" => "manager" })

    assert_equal [["C2", "manager"]], appointments
  end

  test "the same channel twice does not break the write" do
    settle_appointments({ "channel_id" => "C1", "role" => "manager" },
      { "channel_id" => "C1", "role" => "manager" })

    assert_equal [["C1", "manager"]], appointments
  end

  test "an outage leaves what we already hold alone" do
    settle_appointments({ "channel_id" => "C1", "role" => "manager" })
    ENV["PROMETHEUS_BASE_URL"] = UNREACHABLE_URL

    assert_not Prometheus::Mirror.refresh(WHO)
    assert_equal [["C1", "manager"]], appointments
  end

  test "nothing happens when no base url is configured" do
    settle_appointments({ "channel_id" => "C1", "role" => "manager" })
    ENV.delete("PROMETHEUS_BASE_URL")

    assert_not Prometheus::Mirror.refresh(WHO)
    assert_not Prometheus::Mirror.refresh_if_due(WHO)
    assert_equal [["C1", "manager"]], appointments
  end

  test "a reconcile refuses to empty the mirror" do
    settle_appointments({ "channel_id" => "C1", "role" => "manager" })

    stub_roster(:every_appointment, [].each) do
      assert_not Prometheus::Mirror.reconcile_all
    end

    assert_equal [["C1", "manager"]], appointments
  end

  test "a reconcile replaces every row" do
    settle_appointments({ "channel_id" => "COLD", "role" => "manager" })
    rows = [{ "user_id" => "UOTHER01", "channel_id" => "CNEW", "role" => "manager" }]

    stub_roster(:every_appointment, rows.each) do
      assert_equal 1, Prometheus::Mirror.reconcile_all
    end

    assert_empty appointments
    assert_equal [["CNEW", "manager"]], appointments("UOTHER01")
  end

  test "a reconcile that cannot reach Prometheus changes nothing" do
    settle_appointments({ "channel_id" => "C1", "role" => "manager" })
    ENV["PROMETHEUS_BASE_URL"] = UNREACHABLE_URL

    assert_not Prometheus::Mirror.reconcile_all
    assert_equal [["C1", "manager"]], appointments
  end

  test "a second look inside the fresh window does not ask again" do
    original_cache = Rails.cache
    Rails.cache = ActiveSupport::Cache::MemoryStore.new
    settle_appointments({ "channel_id" => "C1", "role" => "manager" })

    assert Prometheus::Mirror.check_due?(WHO)
    assert_not Prometheus::Mirror.check_due?(WHO)
  ensure
    Rails.cache = original_cache
  end

  test "somebody holding no appointment is never looked up" do
    assert_not Prometheus::Mirror.refresh_if_due("UNOBODY9")
  end
end

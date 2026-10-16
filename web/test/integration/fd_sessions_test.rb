require "test_helper"

class FdSessionsTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  WHO = "USUB".freeze
  ALT = "UALT".freeze

  setup do
    @me = grant_role!("UME", "community_manager")
  end

  def agent!(app, os)
    as_pipeline(<<~SQL.squish, "raw agent #{app} #{os}", app, os).first.values.first
      INSERT INTO slack.user_agent (ua, app, os) VALUES (?, ?, ?)
      ON CONFLICT (md5(ua)) DO UPDATE SET app = EXCLUDED.app, os = EXCLUDED.os
      RETURNING id
    SQL
  end

  def signed_in!(user_id, at:, ip: "81.2.69.144", ua_app: "Chrome 141",
    ua_os: "Windows 10 or 11", action: "user_login", source: "audit_logs",
    country: "GB", isp: "Sky", seen: 1)
    outcome_counts = %w[user_login user_login_failed anomaly].map { |one| action == one ? 1 : 0 }
    values = [user_id, source, at, ip, agent!(ua_app, ua_os), at, at, *outcome_counts, country, isp, seen]
    as_pipeline(<<~SQL.squish, *values)
      INSERT INTO fd.login_event AS existing
        (user_id, source, hour, ip, ua_id, first_at, last_at, logins, failures, anomalies,
         country, isp, seen)
      VALUES (?, ?, date_trunc('hour', ?::timestamptz, 'UTC'), ?::inet, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT (user_id, source, hour, ip, ua_id) DO UPDATE SET
        first_at = least(existing.first_at, EXCLUDED.first_at),
        last_at = greatest(existing.last_at, EXCLUDED.last_at),
        hits = existing.hits + 1, logins = existing.logins + EXCLUDED.logins,
        failures = existing.failures + EXCLUDED.failures,
        anomalies = existing.anomalies + EXCLUDED.anomalies, seen = existing.seen + EXCLUDED.seen
    SQL
    seeded!("fd.login_event", "user_id", user_id)
    seeded!("fd.member_trait", "user_id", user_id)
  end

  def shared_ip_prefix!(prefix, member_count)
    as_pipeline(<<~SQL.squish, prefix, member_count)
      INSERT INTO fd.member_trait (user_id, kind, value)
      SELECT 'UCROWD' || n, 'ip_prefix', ? FROM generate_series(1, ?) n
    SQL
    seeded!("fd.member_trait", "value", prefix)
  end

  test "devices groups sign-ins by agent with device_count and address_count" do
    signed_in!(WHO, at: 2.days.ago)
    signed_in!(WHO, at: 1.day.ago, ua_app: "Slack Android 26", ua_os: "Android 14",
      ip: "27.109.113.219", country: "KH", isp: "Smart Axiata")

    sessions = Fd::MemberSessions.new(WHO)
    assert_equal 2, sessions.device_count
    assert_equal 2, sessions.address_count
    assert_includes sessions.devices.map(&:name), "Slack Android 26 · Android 14"
  end

  test "address with one account is alone and not shared" do
    signed_in!(WHO, at: 1.hour.ago)

    address = Fd::MemberSessions.new(WHO).addresses.first
    assert address.alone?
    assert_not address.shared?
    assert_empty address.other_user_ids
  end

  test "address on a small range is shared and lists the other user id" do
    signed_in!(WHO, at: 1.hour.ago)
    signed_in!(ALT, at: 2.hours.ago)

    address = Fd::MemberSessions.new(WHO).addresses.first
    assert address.shared?
    assert_equal [ALT], address.other_user_ids
  end

  test "address in a prefix shared by many users is shared_range? with no other_user_ids" do
    signed_in!(WHO, at: 1.hour.ago)
    signed_in!(ALT, at: 2.hours.ago)
    shared_ip_prefix!("81.2.69.0", 1_240)

    address = Fd::MemberSessions.new(WHO).addresses.first
    assert address.shared_range?
    assert_empty address.other_user_ids, "a shared range must not list other users"
  end

  test "failures and anomalies count failed logins and anomaly events" do
    signed_in!(WHO, at: 3.hours.ago, action: "user_login_failed")
    signed_in!(WHO, at: 2.hours.ago, action: "anomaly")

    sessions = Fd::MemberSessions.new(WHO)
    assert_equal 1, sessions.failures
    assert_equal 1, sessions.anomalies
  end

  test "address country and isp and sign_in_count come from an access_logs row" do
    signed_in!(WHO, at: 1.hour.ago, source: "access_logs", country: "KH",
      isp: "Smart Axiata", seen: 9)

    address = Fd::MemberSessions.new(WHO).addresses.first
    assert_equal "KH", address.country
    assert_equal "Smart Axiata", address.isp
    assert_equal 9, address.sign_in_count
  end

  test "member logins renders the sessions list for a firefighter" do
    signed_in!(WHO, at: 1.hour.ago)
    sign_in_as(grant_role!("UFF", "firefighter"))

    get fd_member_logins_path(WHO)
    assert_response :success
    assert_select ".sessions"
    assert_match "Chrome 141", response.body
  end

  test "member logins renders the member-sessions turbo frame" do
    signed_in!(WHO, at: 1.hour.ago)
    sign_in_as(@me)

    get fd_member_logins_path(WHO)
    assert_select %(turbo-frame#member-sessions-#{WHO}), 1,
      "the response must contain the member-sessions frame"
  end

  test "member logins renders the turbo frame for a member with no sign-ins" do
    sign_in_as(@me)

    get fd_member_logins_path("UEMPTY")
    assert_select %(turbo-frame#member-sessions-UEMPTY), 1
  end

  test "member logins writes one login AccessLog row for the subject" do
    signed_in!(WHO, at: 1.hour.ago)
    sign_in_as(@me)

    assert_difference -> { AccessLog.where(field_class: "login").count }, 1 do
      get fd_member_logins_path(WHO)
    end
    assert_equal WHO, AccessLog.where(field_class: "login").last.subject_user_id
  end

  test "member logins redirects when identity.read is denied" do
    Authz::Override.create!(role: "firefighter", capability: "identity.read",
      allowed: false, changed_by: "UME")
    sign_in_as(grant_role!("UOBS", "firefighter"))

    get fd_member_logins_path(WHO)
    assert_response :redirect
  end

  test "member logins renders the No sessions title for a member with no sign-ins" do
    sign_in_as(@me)

    get fd_member_logins_path("UNOBODY")
    assert_response :success
    assert_select ".empty-title", "No sessions"
  end

  test "member page renders the sessions tab link and a lazy frame without a login AccessLog row" do
    sign_in_as(@me)

    assert_no_difference -> { AccessLog.where(field_class: "login").count } do
      get fd_member_path(WHO)
      assert_select "nav.member-record-tabs a[href=?]", fd_member_path(WHO, tab: "sessions")

      get fd_member_path(WHO, tab: "sessions")
    end
    assert_select %(turbo-frame#member-sessions-#{WHO}[loading="lazy"][src="#{fd_member_logins_path(WHO)}"])
  end
end

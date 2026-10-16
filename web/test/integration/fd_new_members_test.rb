require "test_helper"

class FdNewMembersTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = grant_role!("UME", "community_manager")
  end

  def joined!(user_id, at:, source: "team_join", email: nil)
    member!(user_id, email: email)
    as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) VALUES (?, ?, ?) " \
                "ON CONFLICT (user_id) DO UPDATE SET joined_at = EXCLUDED.joined_at, " \
                "source = EXCLUDED.source", user_id, at, source)
    seeded!("fd.member_joins", "user_id", user_id)
  end

  def query(params = {}, actor: @me)
    Fd::NewMemberQuery.new(params.stringify_keys, actor: actor)
  end

  test "when filter week excludes older joiners and any includes them" do
    joined!("UNEW1", at: 2.hours.ago)
    joined!("UOLD1", at: 40.days.ago)

    assert_includes query({ "when" => "week" }).rows.map(&:user_id), "UNEW1"
    assert_not_includes query({ "when" => "week" }).rows.map(&:user_id), "UOLD1"
    assert_includes query({ "when" => "any" }).rows.map(&:user_id), "UOLD1"
  end

  test "rows expose email and domain to an identity reader and nil email to no actor" do
    joined!("UE1", at: 1.hour.ago, email: "kid@school.example")

    row = query.rows.find { |one| one.user_id == "UE1" }
    assert_equal "kid@school.example", row.email
    assert_equal "school.example", row.domain

    anonymous_query = Fd::NewMemberQuery.new({}, actor: nil)
    assert_nil anonymous_query.rows.find { |one| one.user_id == "UE1" }.email
  end

  test "lone_domain? is true for an unshared domain and false for a shared one" do
    joined!("UD1", at: 1.hour.ago, email: "one@lonely.example")
    joined!("UD2", at: 1.hour.ago, email: "two@shared.example")
    joined!("UD3", at: 2.hours.ago, email: "three@shared.example")

    rows = query.rows.index_by(&:user_id)
    assert rows["UD1"].lone_domain?
    assert_not rows["UD2"].lone_domain?
    assert_equal 2, rows["UD2"].domain_user_count
  end

  test "guarded? and deactivated? separate a shush guard from a deactivation" do
    joined!("UG1", at: 1.hour.ago)
    joined!("UG2", at: 1.hour.ago)
    Fd::MemberGuard.create!(kind: "shush", subject_id: "UG1", opened_by: "UME",
      reason: "spam", enforced_by: "nemo", enforcement_status: "held", expires_at: 2.days.from_now)
    Fd::MemberGuard.create!(kind: "deactivation", subject_id: "UG2", opened_by: "UME",
      reason: "raiding", enforced_by: "nemo", enforcement_status: "held")

    rows = query.rows.index_by(&:user_id)
    assert rows["UG1"].guarded?
    assert_not rows["UG1"].deactivated?
    assert rows["UG2"].deactivated?

    assert_equal ["UG1"], query({ "view" => "guarded" }).rows.map(&:user_id) - ["UG2"]
    assert_equal ["UG2"], query({ "view" => "gone" }).rows.map(&:user_id)
  end

  test "views counts ignore the selected view" do
    joined!("UT1", at: 1.hour.ago)
    joined!("UT2", at: 1.hour.ago + 20.seconds)
    Fd::MemberGuard.create!(kind: "deactivation", subject_id: "UT1", opened_by: "UME",
      reason: "raiding", enforced_by: "nemo", enforcement_status: "held")

    counts = query({ "view" => "gone" }).views.index_by(&:key)
    assert_equal 2, counts["newest"].count
    assert_equal 1, counts["gone"].count
  end

  test "domain filter resets to any without identity access and does not filter rows" do
    joined!("UF1", at: 1.hour.ago, email: "kid@school.example")

    anonymous_query = Fd::NewMemberQuery.new({ "domain" => "school.example" }, actor: nil)
    assert_equal "any", anonymous_query["domain"]
    assert_includes anonymous_query.rows.map(&:user_id), "UF1"
  end

  test "new members index renders the turbo frame with the joiner domain" do
    joined!("UP1", at: 1.hour.ago, email: "kid@school.example")
    sign_in_as(@me)

    get fd_new_members_path
    assert_response :success
    assert_select "turbo-frame#new-members"
    assert_match "school.example", response.body
  end

  test "new members index writes no AccessLog row for a listed email" do
    joined!("UL1", at: 1.hour.ago, email: "kid@school.example")
    sign_in_as(@me)

    assert_no_difference -> { AccessLog.count } do
      get fd_new_members_path
      get fd_new_members_path
    end
  end

  test "window_params keeps view and view_params keeps when" do
    member_query = query({ "view" => "guarded", "when" => "day" })

    assert_equal "guarded", member_query.view, "picking a window must not drop the tab"
    assert_equal "day", member_query["when"]
    assert_equal "guarded", member_query.window_params("month")["view"]
    assert_equal "day", member_query.view_params("gone")["when"]
  end

  test "term is kept by window_params and view_params" do
    member_query = query({ "view" => "guarded", "when" => "day", "q" => "zev" })

    assert_equal "zev", member_query.term
    assert_equal "zev", member_query.window_params("month")["q"]
    assert_equal "zev", member_query.view_params("gone")["q"]
    assert_equal "guarded", member_query.view
  end

  test "q matches user id and matches email only for an identity reader" do
    joined!("US1", at: 1.hour.ago, email: "findme@school.example")

    assert_includes query({ "q" => "us1" }).rows.map(&:user_id), "US1"
    assert_includes query({ "q" => "findme" }).rows.map(&:user_id), "US1"
    anonymous_query = Fd::NewMemberQuery.new({ "q" => "findme" }, actor: nil)
    assert_not_includes anonymous_query.rows.map(&:user_id), "US1"
  end

  test "bulk deactivations create one pending deactivation guard per user" do
    joined!("UX1", at: 1.hour.ago)
    joined!("UX2", at: 1.hour.ago)
    sign_in_as(@me)

    post fd_bulk_deactivations_path, params: {
      user_ids: %w[UX1 UX2], reason: "joined together and posted the same link"
    }

    assert_equal 2, Fd::MemberGuard.where(kind: "deactivation", subject_id: %w[UX1 UX2]).count
    assert_equal %w[pending], Fd::MemberGuard.where(subject_id: %w[UX1 UX2])
      .pluck(:enforcement_status).uniq
  end

  test "bulk deactivations with empty user_ids create no guard and alert" do
    sign_in_as(@me)

    assert_no_difference -> { Fd::MemberGuard.count } do
      post fd_bulk_deactivations_path, params: { user_ids: [], reason: "raiding" }
    end
    assert_match(/Select members/, flash[:alert])
  end

  test "bulk deactivations store the reason and NO_REASON for a blank reason" do
    joined!("UZ1", at: 1.hour.ago)
    joined!("UZ2", at: 1.hour.ago)
    sign_in_as(@me)

    post fd_bulk_deactivations_path, params: { user_ids: %w[UZ1], reason: "invite spam" }
    assert_equal "invite spam", Fd::MemberGuard.find_by(subject_id: "UZ1").reason

    post fd_bulk_deactivations_path, params: { user_ids: %w[UZ2], reason: " " }
    assert_equal Fd::BulkDeactivationsController::NO_REASON,
      Fd::MemberGuard.find_by(subject_id: "UZ2").reason
  end

  test "bulk deactivations create no guard when member.deactivate is denied" do
    joined!("UW1", at: 1.hour.ago)
    Authz::Override.create!(role: "firefighter", capability: "member.deactivate",
      allowed: false, changed_by: "UME")
    sign_in_as(grant_role!("UFF", "firefighter"))

    post fd_bulk_deactivations_path, params: { user_ids: %w[UW1], reason: "raiding" }

    assert_empty Fd::MemberGuard.where(subject_id: "UW1")
  end

  test "bulk deactivations skip a user with a deactivation guard and notify" do
    joined!("UV1", at: 1.hour.ago)
    Fd::MemberGuard.create!(kind: "deactivation", subject_id: "UV1", opened_by: "UME",
      reason: "already", enforced_by: "nemo", enforcement_status: "held")
    sign_in_as(@me)

    post fd_bulk_deactivations_path, params: { user_ids: %w[UV1], reason: "again" }

    assert_equal 1, Fd::MemberGuard.where(subject_id: "UV1").count
    assert_match(/already guarded/, flash[:notice])
  end

  test "rows expose kinds as the guard kind names" do
    joined!("UK1", at: 1.hour.ago)
    Fd::MemberGuard.create!(kind: "shush", subject_id: "UK1", opened_by: "UME",
      reason: "spam", enforced_by: "nemo", enforcement_status: "held", expires_at: 2.days.from_now)

    assert_equal %w[shush], query.rows.find { |row| row.user_id == "UK1" }.kinds
  end

  test "new members index writes no AccessLog row when no email is listed" do
    joined!("UN1", at: 1.hour.ago)
    sign_in_as(@me)

    assert_no_difference -> { AccessLog.count } do
      get fd_new_members_path
    end
  end
end

class FdNewMemberCardTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
    member!("UJOIN", email: "kid@throwaway.example")
    as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) " \
                "VALUES (?, now(), 'team_join') ON CONFLICT (user_id) DO NOTHING", "UJOIN")
    seeded!("fd.member_joins", "user_id", "UJOIN")
    signed_in!("185.26.172.245", "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4_2 like Mac OS X) CriOS/154.0.8037.55",
      "Chrome 154.0.8037.55", "iOS 26.4.2", country: "RS", isp: "TELEKOM SRBIJA a.d.")
    seeded!("fd.login_event", "user_id", "UJOIN")
  end

  def signed_in!(ip, ua, app, os, at: "now()", country: nil, isp: nil)
    as_pipeline(<<~SQL.squish, ua, app, os)
      INSERT INTO slack.user_agent (ua, app, os) VALUES (?, ?, ?) ON CONFLICT (md5(ua)) DO NOTHING
    SQL
    as_pipeline(<<~SQL.squish, "UJOIN", ip, country, isp, ua)
      INSERT INTO fd.login_event (user_id, source, hour, ip, ua_id, first_at, last_at, country, isp)
      SELECT ?, 'audit_logs', date_trunc('hour', #{at}, 'UTC'), ?::inet, agent.id, #{at}, #{at}, ?, ?
      FROM slack.user_agent agent WHERE agent.ua = ?
      ON CONFLICT DO NOTHING
    SQL
  end

  test "new member card renders identity and last sign-in details" do
    get fd_new_member_path("UJOIN")
    assert_response :success

    assert_match "kid@throwaway.example", response.body
    assert_match "UJOIN", response.body
    assert_match "185.26.172.245", response.body
    assert_match "Chrome 154.0.8037.55 on iOS 26.4.2", response.body
    assert_match "Serbia", response.body
    assert_match "TELEKOM SRBIJA", response.body
    assert_match "CriOS/154.0.8037.55", response.body, "the whole agent string is shown"
    assert_match "\u{1F1F7}\u{1F1F8}", response.body, "the flag is drawn from the country"
  end

  test "new members table has IP and Country columns and no On domain or Last seen from column" do
    get fd_new_members_path
    assert_response :success

    assert_select "th", text: "IP"
    assert_select "th", text: "Country"
    assert_select "th", text: "On domain", count: 0
    assert_select "th", text: "Last seen from", count: 0
    assert_match "185.26.172.245", response.body
    assert_match "Serbia", response.body
  end

  test "card keeps the earlier country and uses the newest ip when a sign-in has no country" do
    signed_in!("203.0.113.9", "x", "Chrome 1", "Linux", at: "now() + interval '1 minute'")

    get fd_new_member_path("UJOIN")
    assert_response :success
    assert_match "Serbia", response.body,
      "the country from the earlier row must be kept"
    assert_match "TELEKOM SRBIJA", response.body
    assert_match "203.0.113.9", response.body, "the ip comes from the newest row"
  end

  test "card wraps the email in email_off markers" do
    get fd_new_member_path("UJOIN")
    assert_match "<!--email_off-->", response.body
    assert_match "kid@throwaway.example", response.body

    body = response.body
    off = body.index("<!--email_off-->")
    on = body.index("<!--/email_off-->")
    assert off < body.index("kid@throwaway.example")
    assert on > body.index("kid@throwaway.example"),
      "the email must sit between the email_off markers"
  end

  test "new members index wraps the email in email_off markers" do
    get fd_new_members_path
    assert_match "<!--email_off-->", response.body
    assert_match "kid@throwaway.example", response.body
  end

  test "card renders the turbo frame new-member-card" do
    get fd_new_member_path("UJOIN")
    assert_select %(turbo-frame[id="new-member-card"])
  end

  test "card writes no AccessLog row" do
    assert_no_difference -> { AccessLog.count } do
      get fd_new_member_path("UJOIN")
    end
  end

  test "card for a member with no sign-in renders never signed in" do
    member!("UQUIET")
    as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) " \
                "VALUES (?, now(), 'team_join') ON CONFLICT (user_id) DO NOTHING", "UQUIET")
    seeded!("fd.member_joins", "user_id", "UQUIET")

    get fd_new_member_path("UQUIET")
    assert_response :success
    assert_match "never signed in", response.body
  end

  test "card for an unknown user id returns 404" do
    get fd_new_member_path("UNOBODY")
    assert_response :not_found
  end

  test "card renders for a member who joined 200 days ago" do
    as_pipeline("UPDATE fd.member_joins SET joined_at = now() - interval '200 days' " \
                "WHERE user_id = ?", "UJOIN")

    get fd_new_member_path("UJOIN")
    assert_response :success
    assert_match "185.26.172.245", response.body
  end
end

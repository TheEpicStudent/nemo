require "test_helper"

class FdLinkCompareTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  DEACTIVATED = "UCMPGONE".freeze
  ACTIVE = "UCMPBACK".freeze
  SIGNALS = '{"mailbox_alias": {"value": "kid@gmail.com", "people": 2, "score": 8.0}, ' \
            '"device_agent": {"value": "Slack/4.41 Mac", "people": 2, "score": 3.0}}'.freeze

  setup do
    @me = grant_role!("UCMPBOSS", "community_manager")
    sign_in_as(@me)
    member!(DEACTIVATED, email: "kid@gmail.com")
    member!(ACTIVE, email: "k.i.d+2@gmail.com")
    as_pipeline("UPDATE fd.member SET is_deleted = true WHERE user_id = ?", DEACTIVATED)
    a, b = [DEACTIVATED, ACTIVE].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal, signals) VALUES (?, ?, 11.0, 'mailbox_alias', ?::jsonb)",
      a, b, SIGNALS)
    seeded!("fd.member_link", "a_user_id", a)
    seeded!("fd.member_link_verdict", "a_user_id", a)
    joined!(DEACTIVATED, 20.days.ago)
    joined!(ACTIVE, 2.days.ago)
    as_pipeline(<<~SQL.squish, DEACTIVATED)
      INSERT INTO fd.evidence_snapshot (user_id, deactivated_at, source, actor_id, reason, identity, traits, links)
      VALUES (?, now() - interval '5 days', 'fire_engine', 'UCMPBOSS', 'ban evasion', '{}', '[]', '[]')
    SQL
    seeded!("fd.evidence_snapshot", "user_id", DEACTIVATED)
    [DEACTIVATED, ACTIVE].each do |user_id|
      trait!(user_id, "mailbox", "kid@gmail.com")
      login!(user_id, "81.2.69.144", 1.day.ago)
    end
  end

  def trait!(user_id, kind, value)
    as_pipeline("INSERT INTO fd.member_trait (user_id, kind, value, first_seen, last_seen) VALUES (?, ?, ?, now(), now()) " \
                "ON CONFLICT DO NOTHING", user_id, kind, value)
    seeded!("fd.member_trait", "user_id", user_id)
  end

  def login!(user_id, ip, at)
    as_pipeline(<<~SQL.squish, user_id, at, ip, at, at)
      INSERT INTO fd.login_event (user_id, source, hour, ip, first_at, last_at)
      VALUES (?, 'audit_logs', date_trunc('hour', ?::timestamptz, 'UTC'), ?::inet, ?, ?)
    SQL
    seeded!("fd.login_event", "user_id", user_id)
    seeded!("fd.member_touch", "user_id", user_id)
  end

  def joined!(user_id, at)
    as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) VALUES (?, ?, 'team_join')", user_id, at)
    seeded!("fd.member_joins", "user_id", user_id)
  end

  def attribute(label)
    css_select(".cmp-grid .cmp-row").find { |row| row.at_css(".cmp-key")&.text&.squish == label }
  end

  test "link compare renders heads and rows with shared values marked" do
    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE)
    assert_response :success

    heads = css_select(".cmp-heads .cmp-head")
    assert_equal 2, heads.size
    assert_match "Deactivated", heads.first.text
    assert_match "by @UCMPBOSS", heads.first.text
    assert_match "ban evasion", heads.first.text
    assert_match(/Post-ban join\s+3 d after the ban/, heads.last.text.squish)
    email = attribute("Email")
    assert_match "kid@gmail.com", email.text
    assert_equal 2, email.css(".cmp-value.is-shared").size
    assert email.at_css(".cmp-match .cmp-yes")
    assert_equal 2, attribute("IP").css(".cmp-value.is-shared").size
    assert_equal 1, email.css(".cmp-value").map { |value| value["data-v"] }.uniq.size,
      "both sides share one data-v"
    assert_nil attribute("JA4"), "no JA4 row when neither account has one"
    assert_match "18 d apart", attribute("Joined").text
  end

  test "link compare renders shared JA3 row from anomaly events" do
    [DEACTIVATED, ACTIVE].each do |user_id|
      as_pipeline(<<~SQL.squish, SecureRandom.uuid, 2.days.ago, user_id, { details: { client_ja3_fingerprint: "e7d705a3286e19ea42f587b344ee6865", client_ja4_fingerprint: nil } }.to_json)
        INSERT INTO slack.audit_event (id, at, action, actor_kind, actor_id, ours, payload)
        VALUES (?, ?, 'anomaly', 'user', ?, false, ?::jsonb)
      SQL
      seeded!("slack.audit_event", "actor_id", user_id)
    end

    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE)

    ja3 = attribute("JA3")
    assert_match "e7d705a3286e19ea42f587b344ee6865", ja3.text
    assert_equal 2, ja3.css(".cmp-value.is-shared").size
    assert_nil attribute("JA4"), "no JA4 row when anomaly has no JA4 fingerprint"
  end

  test "link compare renders score band with signal families and weights" do
    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE)

    assert_select ".cmp-score-value", "11.0"
    assert_select ".cmp-score .state", /Certain/
    assert_select ".cmp-families", /Email 8.0 · Device 3.0/
    assert_equal %w[Email Device], css_select(".cmp-family-head > span:first-child").map { |head| head.text.squish }
    assert_select ".cmp-signal", 2
    assert_select ".cmp-signal .cmp-weight", "+8.0"
  end

  test "link compare with variant renders its score and signals and keeps variant in back" do
    a, b = [DEACTIVATED, ACTIVE].sort
    as_pipeline("INSERT INTO fd.member_link_shadow (variant, a_user_id, b_user_id, score, top_signal, signals) " \
                "VALUES ('flat_inbox', ?, ?, 4.0, 'device_agent', ?::jsonb)",
      a, b, '{"device_agent": {"value": "Slack/4.41 Mac", "people": 2, "score": 4.0}}')
    seeded!("fd.member_link_shadow", "a_user_id", a)

    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE, variant: "flat_inbox")

    assert_select ".cmp-score-value", "4.0"
    assert_select ".cmp-variant b", "flat_inbox"
    assert_select ".cmp-signal", 1
    back = css_select("form.px-verdictbar input[name=back]").first["value"]
    assert_includes back, "variant=flat_inbox"

    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE, variant: "live")
    assert_select ".cmp-score-value", "11.0"
    assert_select ".cmp-variant", 0
  end

  test "link verdict create redirects to back and compare marks verdict recorded" do
    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE, back: fd_links_path)
    assert_select "form.px-verdictbar button[name=verdict][data-key='1'][value=same_person]"
    back = css_select("form.px-verdictbar input[name=back]").first["value"]

    post fd_link_verdicts_path, params: { a: DEACTIVATED, b: ACTIVE, verdict: "same_person", back: back }
    assert_redirected_to back
    follow_redirect!
    assert_select "form.px-verdictbar button[aria-pressed=true]", /Same person/
    assert_select ".cmp-recorded .state", "Same person"
  end

  test "link compare renders deactivate as alt modal for the active account" do
    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE)

    assert_select "form.px-verdictbar button[data-modal-open=member-deactivate][data-key=d]", /Deactivate .* as alt/
    assert_select ".modal-host[data-modal-id-value=member-deactivate] form[action=?]", fd_member_guards_path(ACTIVE)
    assert_select ".modal-host[data-modal-id-value=member-deactivate] textarea[name=reason]", /Alt of/
  end

  test "link compare activity log splits accounts by side and marks same IP within 1 h" do
    as_pipeline("INSERT INTO fd.ip_network (ip_prefix, asn, network, country, class, source) " \
                "VALUES ('81.2.69.0/24', 64500, 'Example Net', 'GB', 'stable', 'ipinfo') ON CONFLICT DO NOTHING")
    seeded!("fd.ip_network", "ip_prefix", "81.2.69.0/24")
    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE)

    rows = css_select(".cmp-log-row:not(.cmp-log-heads)")
    left = rows.map { |row| row.css(".cmp-log-side")[0].text.squish }
    right = rows.map { |row| row.css(".cmp-log-side")[1].text.squish }
    assert_includes left, "Joined"
    assert_includes left, "Deactivated by @UCMPBOSS"
    assert_includes right, "Joined 3 d after the ban"
    assert_equal 2, css_select(".cmp-event.is-shared").size
    assert(css_select(".cmp-event.is-shared").all? { |event| event.text.include?("same IP within 1 h") })
    assert(css_select(".cmp-event.is-shared").all? { |event| event.text.include?("Stable") })
  end

  test "link compare without identity.read hides email and IP and marks IP match" do
    firefighter = grant_role!("UCMPFF", "firefighter")
    override_capability!("firefighter", "identity.read", false, by: "UCMPBOSS")
    sign_in_as(firefighter)

    get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE)
    assert_response :success
    assert_no_match "kid@gmail.com", response.body
    assert_no_match "81.2.69.144", response.body
    assert attribute("IP").at_css(".cmp-match .cmp-yes")
  end

  test "link compare creates one AccessLog row per account" do
    assert_difference -> { AccessLog.where(field_class: "links", subject_user_id: [DEACTIVATED, ACTIVE]).count }, 2 do
      get fd_link_compare_path(a: DEACTIVATED, b: ACTIVE)
    end
  end

  test "link compare with identical a and b returns not found" do
    get fd_link_compare_path(a: DEACTIVATED, b: DEACTIVATED)
    assert_response :not_found
  end
end

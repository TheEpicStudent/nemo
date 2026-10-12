require "test_helper"

class FdLinkCompareTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  GONE = "UCMPGONE".freeze
  BACK = "UCMPBACK".freeze
  SIGNALS = '{"mailbox_alias": {"value": "kid@gmail.com", "people": 2, "score": 8.0}, ' \
            '"device_agent": {"value": "Slack/4.41 Mac", "people": 2, "score": 3.0}}'.freeze

  setup do
    @me = hold_role!("UCMPBOSS", "community_manager")
    sign_in_as(@me)
    member!(GONE, email: "kid@gmail.com")
    member!(BACK, email: "k.i.d+2@gmail.com")
    as_pipeline("UPDATE fd.member SET is_deleted = true WHERE user_id = ?", GONE)
    a, b = [GONE, BACK].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal, signals) VALUES (?, ?, 11.0, 'mailbox_alias', ?::jsonb)",
      a, b, SIGNALS)
    seeded!("fd.member_link", "a_user_id", a)
    seeded!("fd.member_link_verdict", "a_user_id", a)
    joined!(GONE, 20.days.ago)
    joined!(BACK, 2.days.ago)
    as_pipeline(<<~SQL.squish, GONE)
      INSERT INTO fd.evidence_snapshot (user_id, deactivated_at, source, actor_id, reason, identity, traits, links)
      VALUES (?, now() - interval '5 days', 'fire_engine', 'UCMPBOSS', 'ban evasion', '{}', '[]', '[]')
    SQL
    seeded!("fd.evidence_snapshot", "user_id", GONE)
    [GONE, BACK].each do |user_id|
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

  test "compare lines both accounts up row by row with the values they share" do
    get fd_link_compare_path(a: GONE, b: BACK)
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
      "the same value carries one key on both sides"
    assert_nil attribute("JA4"), "a row neither account has is left out"
    assert_match "18 d apart", attribute("Joined").text
  end

  test "the score shows its band and the families behind it, and the signals add up by family" do
    get fd_link_compare_path(a: GONE, b: BACK)

    assert_select ".cmp-score-value", "11.0"
    assert_select ".cmp-score .state", /Certain/
    assert_select ".cmp-families", /Email 8.0 · Device 3.0/
    assert_equal %w[Email Device], css_select(".cmp-family-head > span:first-child").map { |head| head.text.squish }
    assert_select ".cmp-signal", 2
    assert_select ".cmp-signal .cmp-weight", "+8.0"
  end

  test "the floating bar records a verdict and comes back to compare" do
    get fd_link_compare_path(a: GONE, b: BACK, back: fd_links_path)
    assert_select "form.px-verdictbar button[name=verdict][data-key='1'][value=same_person]"
    back = css_select("form.px-verdictbar input[name=back]").first["value"]

    post fd_link_verdicts_path, params: { a: GONE, b: BACK, verdict: "same_person", back: back }
    assert_redirected_to back
    follow_redirect!
    assert_select "form.px-verdictbar button[aria-pressed=true]", /Same person/
    assert_select ".cmp-recorded .state", "Same person"
  end

  test "the bar deactivates the active account as an alt of the deactivated one" do
    get fd_link_compare_path(a: GONE, b: BACK)

    assert_select "form.px-verdictbar button[data-modal-open=member-deactivate][data-key=d]", /Deactivate .* as alt/
    assert_select ".modal-host[data-modal-id-value=member-deactivate] form[action=?]", fd_member_guards_path(BACK)
    assert_select ".modal-host[data-modal-id-value=member-deactivate] textarea[name=reason]", /Alt of/
  end

  test "the activity log puts each account on its side and marks sign-ins from one address within the hour" do
    as_pipeline("INSERT INTO fd.ip_network (ip_prefix, asn, network, country, class, source) " \
                "VALUES ('81.2.69.0/24', 64500, 'Example Net', 'GB', 'stable', 'ipinfo') ON CONFLICT DO NOTHING")
    seeded!("fd.ip_network", "ip_prefix", "81.2.69.0/24")
    get fd_link_compare_path(a: GONE, b: BACK)

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

  test "without identity.read the email and addresses are hidden but still matched" do
    firefighter = hold_role!("UCMPFF", "firefighter")
    move_capability!("firefighter", "identity.read", false, by: "UCMPBOSS")
    sign_in_as(firefighter)

    get fd_link_compare_path(a: GONE, b: BACK)
    assert_response :success
    assert_no_match "kid@gmail.com", response.body
    assert_no_match "81.2.69.144", response.body
    assert attribute("IP").at_css(".cmp-match .cmp-yes")
  end

  test "reading a pair is logged against both accounts" do
    assert_difference -> { AccessLog.where(field_class: "links", subject_user_id: [GONE, BACK]).count }, 2 do
      get fd_link_compare_path(a: GONE, b: BACK)
    end
  end

  test "a pair needs two distinct member IDs" do
    get fd_link_compare_path(a: GONE, b: GONE)
    assert_response :not_found
  end
end

require "test_helper"

class FdOverviewTest < ActionDispatch::IntegrationTest
  setup do
    @me = Account.create!(user_id: "UFF1")
    grant_role!("UFF1", "firefighter")
    sign_in_as(@me)

    AccessLog.create!(actor_id: "UOTHER", subject_user_id: "USUB",
      field_class: "identity", looked_at: 1.hour.ago)
  end

  test "overview with access logs from other actors returns success" do
    get fd_root_path

    assert_response :success
  end
  def guard!(**over)
    Fd::MemberGuard.create!({
      kind: "shush", subject_id: "USUB", opened_by: "UMOD",
      reason: "being awful", expires_at: 7.days.from_now
    }.merge(over))
  end

  def panel
    response.body[/In force now.*?<\/section>/m]
  end

  def metric
    response.body[/In force<\/span>\s*<span class="metric-value">(\d+)/, 1]
  end

  test "overview without guards shows zero in force and no panel" do
    get fd_root_path
    assert_equal "0", metric
    assert_match(/<span>none<\/span>/, response.body)
    assert_nil panel
  end

  test "overview with a guard without a case counts it and shows attached to no case" do
    guard!
    get fd_root_path
    assert_equal "1", metric
    assert_match(/attached to no case/, response.body)
    assert_match(%r{<span class="na">None</span>}, panel)
  end

  test "overview with every guard linked to a case shows all linked to a case" do
    guard!(case_id: make_case.id)
    get fd_root_path
    assert_match(/all linked to a case/, response.body)
    assert_no_match(/attached to no case/, response.body)
  end

  test "in_force panel with dates outside current year includes year" do
    opened = Time.zone.local(Date.current.year - 1, 3, 3, 12)
    expiry = Time.zone.local(Date.current.year + 1, 10, 15, 12)
    guard!(opened_at: opened, expires_at: expiry)

    get fd_root_path

    assert_includes panel, "3 Mar #{opened.year}"
    assert_includes panel, "15 Oct #{expiry.year}"
  end

  test "overview excludes a lifted guard from in force" do
    guard!(state: "lifted", lifted_at: Time.current, lifted_by: "UMOD")
    get fd_root_path
    assert_equal "0", metric
    assert_nil panel
  end

  test "overview panel shows the enforcement status of each guard" do
    guard!
    guard!(kind: "channel_ban", channel_id: "C0266FRGV", subject_id: "UTWO", enforcement_status: "failed")
    guard!(subject_id: "UTHREE", enforced_by: "by_hand", enforcement_status: "held")
    get fd_root_path

    assert_equal "3", metric
    assert_match(/Pending/, panel)
    assert_match(/Not enforced/, panel)
    assert_match(/By hand/, panel)
  end

  test "overview panel lists the channel_ban guard before the shush guard" do
    guard!(kind: "channel_ban", channel_id: "C0266FRGV", subject_id: "UBAN")
    guard!(subject_id: "USHUSH")
    get fd_root_path

    assert_operator panel.index("UBAN"), :<, panel.index("USHUSH")
  end

  test "overview panel shows no end date for a guard without expires_at" do
    guard!(expires_at: nil)
    get fd_root_path
    assert_match(/no end date/, panel)
  end
end

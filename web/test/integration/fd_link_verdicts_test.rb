require "test_helper"

class FdLinkVerdictsTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  ACTIVE = "UVACTIVE".freeze
  DELETED = "UVGONE".freeze

  setup do
    @me = hold_role!("UME", "community_manager")
    sign_in_as(@me)
    member!(ACTIVE)
    member!(DELETED)
    as_pipeline("UPDATE fd.member SET is_deleted = true WHERE user_id = ?", DELETED)
    a, b = [ACTIVE, DELETED].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal) VALUES (?, ?, 9.0, 'ip_stable')",
      a, b)
    seeded!("fd.member_link", "a_user_id", a)
    seeded!("fd.member_link_verdict", "a_user_id", a)
  end

  def post_verdict(verdict, note: nil, back: fd_links_path)
    post fd_link_verdicts_path, params: { a: DELETED, b: ACTIVE, verdict: verdict, note: note, back: back }
  end

  def compare_href = fd_link_compare_path(a: [ACTIVE, DELETED].min, b: [ACTIVE, DELETED].max, back: fd_links_path)

  test "a pair is judged from compare and leaves the unreviewed list" do
    get fd_links_path
    assert_select "a.btn[href=?]", compare_href, text: "Review"

    get compare_href
    assert_select "form.px-verdictbar button[name=verdict]", 3
    assert_select "form.px-verdictbar input[name=back]"

    assert_difference -> { Fd::LinkVerdict.count }, 1 do
      post_verdict("different_people", note: "cousins")
    end
    assert_redirected_to fd_links_path
    assert_equal "verdict recorded", flash[:notice]
    follow_redirect!
    assert_select "a.btn[href=?]", compare_href, count: 0

    row = Fd::LinkVerdict.find_by!(a_user_id: [ACTIVE, DELETED].min, b_user_id: [ACTIVE, DELETED].max)
    assert_equal ["different_people", "UME", "cousins"], [row.verdict, row.decided_by, row.note]
  end

  test "a verdict is written to the audit log like the command writes it" do
    post_verdict("same_person")

    entry = Fd::AuditEntry.where(entity_type: "member_link_verdict").order(:id).last
    assert_equal "linked", entry.verb
    assert_equal "UME", entry.actor_user_id
    assert_equal [ACTIVE, DELETED].max, entry.subject_user_id
    assert_equal "same_person", entry.after["verdict"]
    assert_nil entry.before
  end

  test "a changed verdict keeps what it said before" do
    post_verdict("same_person", note: "dm")
    post_verdict("different_people")

    entry = Fd::AuditEntry.where(entity_type: "member_link_verdict").order(:id).last
    assert_equal "unlinked", entry.verb
    assert_equal "same_person", entry.before["verdict"]
    assert_equal "dm", Fd::LinkVerdict.last.note, "an empty note keeps the one already given"
    assert_match "verdict changed", flash[:notice]
  end

  test "saying the same thing twice writes nothing" do
    post_verdict("allowed_alt")
    assert_no_difference -> { Fd::AuditEntry.where(entity_type: "member_link_verdict").count } do
      post_verdict("allowed_alt")
    end
    assert_match "verdict unchanged", flash[:notice]
  end

  test "a judged pair shows its verdict under reviewed and can be changed" do
    post_verdict("allowed_alt")

    get fd_links_path(view: "reviewed")
    assert_select ".link-table .state", "Allowed alt"
    assert_select ".link-table a.btn", "Change"
  end

  test "the member pane and the cluster page judge pairs too" do
    get fd_member_links_path(ACTIVE)
    assert_select "a.btn[href=?]", fd_link_compare_path(a: ACTIVE, b: DELETED, back: fd_member_path(ACTIVE, tab: "links")),
      text: "Review"

    as_pipeline("INSERT INTO fd.member_cluster (user_id, cluster_id, accounts, active) VALUES (?, ?, 2, true), (?, ?, 2, false)",
      ACTIVE, DELETED, DELETED, DELETED)
    seeded!("fd.member_cluster", "cluster_id", DELETED)
    get fd_cluster_path(DELETED, tab: "links")
    assert_select ".link-table a.btn", "Review"
  end

  test "a judgement comes back to the page it was made on" do
    post_verdict("same_person", back: fd_member_path(ACTIVE, do: "links"))
    assert_redirected_to fd_member_path(ACTIVE, do: "links")

    post_verdict("different_people", back: "https://elsewhere.example/steal")
    assert_redirected_to fd_links_path
  end

  test "a verdict needs two accounts and one of the three answers" do
    post fd_link_verdicts_path, params: { a: ACTIVE, b: ACTIVE, verdict: "same_person" }
    assert_equal "pick two accounts", flash[:alert]

    post fd_link_verdicts_path, params: { a: ACTIVE, b: DELETED, verdict: "maybe" }
    assert_equal "pick a verdict", flash[:alert]
  end

  test "somebody without link.verdict sees no buttons and is refused" do
    move_capability!("firefighter", "link.verdict", false, by: "UME")
    sign_in_as(hold_role!("UFF", "firefighter"))

    get fd_links_path
    assert_select ".link-table a.btn", "Compare"
    get compare_href
    assert_response :success
    assert_select "form.px-verdictbar", 0

    assert_no_difference -> { Fd::LinkVerdict.count } do
      post_verdict("same_person")
    end
  end
end

require "test_helper"

class FdMemberViewsTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = hold_role!("UVIEWBOSS", "community_manager")
    sign_in_as(@me)
    %w[UVIEWLINKA UVIEWLINKB UVIEWWEAK UVIEWGONE UVIEWPLAIN].each { |user_id| member!(user_id) }
    as_pipeline("UPDATE fd.member SET is_deleted = true WHERE user_id = 'UVIEWGONE'")
    link!("UVIEWLINKA", "UVIEWLINKB", 9.0)
    link!("UVIEWPLAIN", "UVIEWWEAK", 3.5)
    Rails.cache.delete("fd/member_query/view_counts")
  end

  def link!(one, two, score)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal) VALUES (?, ?, ?, 'ip_stable')", a, b, score)
    seeded!("fd.member_link", "a_user_id", a)
  end

  def user_ids(view, term = nil)
    Fd::MemberQuery.new({ "view" => view, "q" => term }.compact, actor: @me).rows.map(&:user_id)
  end

  test "the tabs follow the investigation workspace" do
    get fd_members_path

    tabs = css_select("nav.views a.view").map { |tab| tab.text.squish.sub(/\s*[\d,]+\z/, "") }
    assert_equal ["All", "Linked", "In force", "Deactivated"], tabs
  end

  test "linked keeps members with a strong or certain link" do
    linked = user_ids("linked")

    assert_includes linked, "UVIEWLINKA"
    assert_includes linked, "UVIEWLINKB"
    assert_not_includes linked, "UVIEWWEAK"
    assert_not_includes linked, "UVIEWPLAIN"
  end

  test "deactivated lists deactivated members the other views leave out" do
    assert_includes user_ids("deactivated", "UVIEWGONE"), "UVIEWGONE"
    assert_not_includes user_ids("deactivated", "UVIEWPLAIN"), "UVIEWPLAIN"
    assert_not_includes Fd::MemberQuery.new({ "view" => "deactivated" }, actor: @me).rows.map(&:user_id), "UVIEWPLAIN"
    assert_operator Fd::MemberQuery.new({}).send(:counts_per_view).fetch("deactivated"), :>=, 1
  end
end

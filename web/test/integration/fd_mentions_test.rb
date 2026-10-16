require "test_helper"

class FdMentionsTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    @kase = make_case
    @named = Fd::Member.live.order(:user_id).first
    sign_in_as(@me)
  end

  test "case notes create converts @user_id to a Slack mention" do
    post fd_case_notes_path(@kase), params: { about: "case", body: "spoke to @#{@named.user_id}" }

    assert_equal "spoke to <@#{@named.user_id}>", @kase.notes.sole.body
  end

  test "member notes create converts @user_id to a Slack mention" do
    post fd_member_notes_path("UPRIOR"), params: { body: "watch them near @#{@named.user_id}" }

    assert_equal "watch them near <@#{@named.user_id}>", Fd::Note.for_subject("UPRIOR").sole.body

    get fd_member_path("UPRIOR")
  end

  test "cases create converts @user_id in body to a Slack mention in the case chat" do
    post fd_cases_path, params: { subject_user_ids: ["USUBJ01"],
                                  body: "reported by @#{@named.user_id}" }

    opened = Fd::Case.order(:id).last
    assert_equal "reported by <@#{@named.user_id}>",
      Fd::CaseChat.where(case_id: opened.id).sole.body
  end
end

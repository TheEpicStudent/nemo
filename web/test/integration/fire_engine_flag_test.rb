require "test_helper"

class FireEngineFlagTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
    Fd::Flag.delete_all
    Current.forget_flags
  end

  teardown do
    Fd::Flag.delete_all
    Current.forget_flags
  end

  def disable_fire_engine
    Fd::Flag.set!(:fire_engine, false, by: @me.user_id)
  end

  test "disabled fire_engine flag redirects every fire engine page to root" do
    disable_fire_engine
    kase = make_case

    [fd_cases_path, fd_case_path(kase), fd_members_path, fd_search_path].each do |path|
      get path
      assert_redirected_to root_path
      assert_match(/Fire Engine turned off/, flash[:alert])
    end
  end

  test "disabled fire_engine flag redirects note create and creates no note" do
    disable_fire_engine
    kase = make_case

    assert_no_difference "Fd::Note.count" do
      post fd_case_notes_path(kase), params: { body: "while the section is off" }
    end
    assert_redirected_to root_path
  end

  test "disabled fire_engine flag keeps admin flags page and flag update working" do
    disable_fire_engine

    get admin_flags_path
    assert_response :success

    patch fd_flag_path(key: "fire_engine", on: "1")
    assert Fd::Flag.on?(:fire_engine), "flag update must re-enable fire_engine"
  end

  test "disabled fire_engine and analytics flags redirect to account" do
    disable_fire_engine
    Fd::Flag.set!(:analytics, false, by: @me.user_id)

    get fd_cases_path
    assert_redirected_to account_path

    get root_path
    assert_redirected_to account_path
  end

  test "disabling fire_engine keeps cases and re-enabling serves them" do
    kase = make_case
    disable_fire_engine

    assert Fd::Case.exists?(kase.id)

    Fd::Flag.set!(:fire_engine, true, by: @me.user_id)
    get fd_case_path(kase)
    assert_response :success
  end
end

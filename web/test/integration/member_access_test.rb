require "test_helper"

class MemberAccessTest < ActionDispatch::IntegrationTest
  SCOPE = "channel_manager".freeze
  REASON = "a slack bot that routes design questions".freeze

  setup do
    Fd::Flag.set!(:public_api, true, by: "UBOSS")
    @member = Account.create!(user_id: "UASK1")
    @reviewer = grant_role!("UREV1", "community_manager")
    sign_in_as(@member)
  end

  teardown do
    Fd::Flag.delete_all
    Current.forget_flags
  end

  def register(name: "Triage Bot", blurb: "routes design questions", reason: REASON, scope: SCOPE)
    post settings_apps_path,
      params: { name: name, blurb: blurb, scope: scope, reason: reason }
  end

  test "app registration creates one app and one pending access request" do
    assert_difference -> { Api::App.count }, 1 do
      assert_difference -> { Api::AccessRequest.count }, 1 do
        register
      end
    end

    app = Api::App.sole
    assert_equal [@member.user_id, "Triage Bot", "triage-bot"],
      [app.owner_user_id, app.name, app.slug]
    assert_equal "pending", Api::AccessRequest.sole.state
    assert_equal "access_requested", Api::Event.last.verb
  end

  test "registering the same name twice gives slugs triage-bot and triage-bot-2" do
    register
    register

    assert_equal %w[triage-bot triage-bot-2], Api::App.order(:id).pluck(:slug)
  end

  test "app registration with an invalid blurb creates no app and alerts" do
    assert_no_difference -> { Api::App.count } do
      register(blurb: "bot")
    end

    assert_match(/Enter a description/, flash[:alert])
  end

  test "app registration with an invalid reason creates no app and alerts" do
    assert_no_difference -> { Api::App.count } do
      register(reason: "pls")
    end

    assert_match(/Enter a reason/, flash[:alert])
  end

  test "token create for an unapproved app creates no token and alerts" do
    register
    app = Api::App.sole

    assert_no_difference -> { Api::Token.count } do
      post settings_tokens_path, params: { app_id: app.id, name: "Toolbox" }
    end

    assert_match(/App not approved/, flash[:alert])
  end

  test "token create for another owner's app creates no token and alerts" do
    other_app = make_app!("UOTHER9", name: "Theirs")

    assert_no_difference -> { Api::Token.count } do
      post settings_tokens_path, params: { app_id: other_app.id, name: "Toolbox" }
    end

    assert_match(/Not your app/, flash[:alert])
  end

  test "requests index redirects a member to keys and succeeds for a reviewer" do
    get settings_requests_path
    assert_redirected_to settings_keys_path

    sign_in_as(@reviewer)
    get settings_requests_path
    assert_response :success
  end

  test "approve sets state approved and an active approval and allows token create" do
    register
    access_request = Api::AccessRequest.sole

    sign_in_as(@reviewer)
    post settle_settings_request_path(access_request), params: { verdict: "Approve" }

    assert_equal "approved", access_request.reload.state
    assert Api::Approval.active?(access_request.app_id)

    sign_in_as(@member)
    assert_difference -> { Api::Token.count }, 1 do
      post settings_tokens_path, params: { app_id: access_request.app_id, name: "Toolbox" }
    end
  end

  test "decline sets state declined with the note and leaves no active approval" do
    register
    access_request = Api::AccessRequest.sole

    sign_in_as(@reviewer)
    post settle_settings_request_path(access_request), params: { verdict: "Decline", note: "no" }

    assert_equal ["declined", "no"], [access_request.reload.state, access_request.note]
    assert_not Api::Approval.active?(access_request.app_id)
  end

  test "withdraw ignores a non-owner and withdraws for the owner" do
    register
    access_request = Api::AccessRequest.sole

    sign_in_as(Account.create!(user_id: "UASK2"))
    delete withdraw_settings_request_path(access_request)
    assert_equal "pending", access_request.reload.state

    sign_in_as(@member)
    delete withdraw_settings_request_path(access_request)
    assert_equal "withdrawn", access_request.reload.state
  end

  test "channel manager API returns withheld for an app without its own consent" do
    consented_app = make_app!(@member.user_id, name: "Mine")
    requesting_app = make_app!("UOTHER9", name: "Theirs")
    _token, key = Api::Token.mint!(requesting_app, "Toolbox")
    Api::Consent.set!("USUBJECT1", consented_app.id, SCOPE, true, via: "dashboard")

    get "/api/v1/channels/C0DESIGN99/managers/USUBJECT1",
      headers: { "Authorization" => "Bearer #{key}" }

    assert_response :success
    assert_equal "withheld", response.parsed_body["consent"],
      "consent for one app must not answer for another"
  end

  test "channel manager API returns granted for an app with consent" do
    requesting_app = make_app!("UOTHER9", name: "Theirs")
    _token, key = Api::Token.mint!(requesting_app, "Toolbox")
    Api::Consent.set!("USUBJECT1", requesting_app.id, SCOPE, true, via: "dashboard")

    get "/api/v1/channels/C0DESIGN99/managers/USUBJECT1",
      headers: { "Authorization" => "Bearer #{key}" }

    assert_response :success
    assert_equal "granted", response.parsed_body["consent"]
  end

  test "channel manager API returns 403 not_approved after Api::Approval.revoke!" do
    app = make_app!(@member.user_id)
    Api::Consent.set!("USUBJECT1", app.id, SCOPE, true, via: "dashboard")
    _token, key = Api::Token.mint!(app, "Toolbox")

    get "/api/v1/channels/C0DESIGN99/managers/USUBJECT1",
      headers: { "Authorization" => "Bearer #{key}" }
    assert_response :success

    Api::Approval.revoke!(app.id, by: @reviewer.user_id)

    get "/api/v1/channels/C0DESIGN99/managers/USUBJECT1",
      headers: { "Authorization" => "Bearer #{key}" }
    assert_response :forbidden
    assert_equal "not_approved", response.parsed_body["error"]
  end

  test "retiring an app marks it retired and revokes its tokens and approval" do
    app = make_app!(@member.user_id)
    token, = Api::Token.mint!(app, "Toolbox")

    delete settings_app_path(app)

    assert_predicate app.reload, :retired?
    assert_predicate token.reload, :revoked?
    assert_not Api::Approval.active?(app.id)
  end

  test "retiring an app withdraws its request and removes it from the queue" do
    register
    access_request = Api::AccessRequest.sole

    delete settings_app_path(access_request.app)

    assert_equal "withdrawn", access_request.reload.state
    assert_empty Api::AccessRequest.queue

    sign_in_as(@reviewer)
    get settings_requests_path
    assert_select ".data-table tbody .text-btn", { text: "Review", count: 0 },
      "a retired app must not appear in the review queue"
  end

  test "queue excludes requests for a retired app" do
    register
    access_request = Api::AccessRequest.sole
    access_request.app.update!(retired_at: Time.current)

    assert_empty Api::AccessRequest.queue
  end

  test "rotate keeps the token row and replaces the secret" do
    app = make_app!(@member.user_id)
    token, old_secret = Api::Token.mint!(app, "Toolbox")

    assert_no_difference -> { Api::Token.count } do
      post rotate_settings_token_path(token)
    end

    new_secret = css_select(".secret code").sole.text
    assert_not_equal old_secret, new_secret
    assert_equal Api::Token.digest_of(new_secret), token.reload.digest
    assert_equal "Toolbox", token.name
    assert_not_nil token.rotated_at
  end
end

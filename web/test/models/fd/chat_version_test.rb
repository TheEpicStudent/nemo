require "test_helper"

class Fd::ChatVersionTest < ActiveSupport::TestCase
  setup { @kase = make_case }

  def chat(body = "on it")
    Fd::CaseChat.create!(case_id: @kase.id, author_user_id: "UME", body: body,
      source_app: "fire_engine")
  end

  test "for returns the zero version for a case without messages" do
    assert_equal "0.0.0-0.0.0-0.0.0-0.0.0-0.0.0", Fd::ChatVersion.for(@kase.id)
  end

  test "for changes after a message is created" do
    before = Fd::ChatVersion.for(@kase.id)
    chat
    assert_not_equal before, Fd::ChatVersion.for(@kase.id)
  end

  test "for changes after a message is destroyed" do
    row = chat
    before = Fd::ChatVersion.for(@kase.id)
    row.destroy!
    assert_not_equal before, Fd::ChatVersion.for(@kase.id)
  end

  test "for is unchanged after a last_seen_at update" do
    row = chat
    before = Fd::ChatVersion.for(@kase.id)
    row.update_columns(last_seen_at: 1.minute.from_now)
    assert_equal before, Fd::ChatVersion.for(@kase.id)
  end
end

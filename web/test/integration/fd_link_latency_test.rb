require "test_helper"

class FdLinkLatencyTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  ONE = "ULATONE".freeze
  TWO = "ULATTWO".freeze
  UPSERT = <<~SQL.squish.freeze
    INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal, computed_at)
    VALUES (?, ?, ?, 'mailbox_alias', now())
    ON CONFLICT (a_user_id, b_user_id) DO UPDATE SET score = EXCLUDED.score, computed_at = EXCLUDED.computed_at
  SQL

  def link!(score)
    as_pipeline(UPSERT, ONE, TWO, score)
    seeded!("fd.member_link", "a_user_id", ONE)
  end

  def linked_at
    as_pipeline("SELECT linked_at FROM fd.member_link WHERE a_user_id = ? AND b_user_id = ?", ONE, TWO).first["linked_at"]
  end

  def joined!(user_id, at)
    as_pipeline("INSERT INTO fd.member_joins (user_id, joined_at, source) VALUES (?, ?, 'team_join')", user_id, at)
    seeded!("fd.member_joins", "user_id", user_id)
  end

  test "member_link upsert sets linked_at once and keeps it on rewrite" do
    link!(9.0)
    first = linked_at
    assert first.present?

    link!(11.0)
    assert_equal first, linked_at
    assert_equal 11.0, as_pipeline("SELECT score FROM fd.member_link WHERE a_user_id = ?", ONE).first["score"].to_f
  end

  test "link_latency computes seconds from the later join and the last sign-in" do
    joined!(ONE, 3.days.ago)
    joined!(TWO, 90.seconds.ago)
    sign_in = 30.seconds.ago
    as_pipeline(<<~SQL.squish, TWO, sign_in, sign_in, sign_in)
      INSERT INTO fd.login_event (user_id, source, hour, ip, first_at, last_at)
      VALUES (?, 'audit_logs', date_trunc('hour', ?::timestamptz, 'UTC'), '81.2.69.144'::inet, ?, ?)
    SQL
    seeded!("fd.login_event", "user_id", TWO)
    seeded!("fd.member_trait", "user_id", TWO)
    seeded!("fd.member_touch", "user_id", TWO)
    link!(9.0)

    row = as_pipeline("SELECT * FROM fd.link_latency WHERE a_user_id = ?", ONE).first
    assert_in_delta 90, row["from_join_seconds"].to_f, 15
    assert_in_delta 30, row["from_sign_in_seconds"].to_f, 15
  end

  test "link_latency excludes links with linked_at older than a week" do
    link!(9.0)
    as_pipeline("UPDATE fd.member_link SET linked_at = now() - interval '8 days' WHERE a_user_id = ?", ONE)

    assert_empty as_pipeline("SELECT 1 FROM fd.link_latency WHERE a_user_id = ?", ONE).to_a
  end
end

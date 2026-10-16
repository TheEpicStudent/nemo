require "test_helper"

class Fd::MemberFinderTest < ActiveSupport::TestCase
  include SeedsPipelineTables

  setup do
    @staff = grant_role!("UFINDER1", "community_manager")
  end

  def named!(user_id, display_name, handle: nil, real_name: nil, email: nil, deleted: false, bot: false)
    as_pipeline("INSERT INTO fd.member (user_id, handle, display_name, is_deleted, is_bot) " \
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET handle = EXCLUDED.handle, " \
                "display_name = EXCLUDED.display_name, is_deleted = EXCLUDED.is_deleted, " \
                "is_bot = EXCLUDED.is_bot",
      user_id, handle || user_id.downcase, display_name, deleted, bot)
    seeded!("fd.member", "user_id", user_id)
    if real_name || email
      as_pipeline("INSERT INTO fd.member_identity (user_id, real_name, email) VALUES (?, ?, ?) " \
                  "ON CONFLICT (user_id) DO UPDATE SET real_name = EXCLUDED.real_name, " \
                  "email = EXCLUDED.email", user_id, real_name, email)
      seeded!("fd.member_identity", "user_id", user_id)
    end
    user_id
  end

  def find_members(term, actor: @staff, limit: 20)
    Fd::MemberFinder.new(term, actor: actor).find(limit: limit)
  end

  test "find with a pasted id format returns exactly that member" do
    named!("U0ZQ7Y4KD1", "Zorblax Quintrell")
    named!("U0ZQ7Y4KD2", "Zorblax Quintrell Jr")

    ["U0ZQ7Y4KD1", "u0zq7y4kd1", "@U0ZQ7Y4KD1", "<@U0ZQ7Y4KD1>", "<@U0ZQ7Y4KD1|zorblax>",
     "https://hackclub.slack.com/team/U0ZQ7Y4KD1"].each do |input|
      assert_equal ["U0ZQ7Y4KD1"], find_members(input).ids, input
      assert_equal 1, find_members(input).total, input
    end
  end

  test "find with an unknown id returns no ids and does not match names" do
    named!("U0ZQ7Y4KD1", "U0NOBODY99 fan club")

    assert_empty find_members("U0NOBODY99").ids
  end

  test "find with an id returns a member that only appears in a case" do
    make_case(subject: "U0CASEONLY", opened_at: 2.days.ago)

    assert_equal ["U0CASEONLY"], find_members("U0CASEONLY").ids
  end

  test "find matches words in any order" do
    named!("U0ZQ7Y4KD1", "Zorblax Quintrell")

    assert_includes find_members("quintrell zorblax").ids, "U0ZQ7Y4KD1"
    assert_includes find_members("zorb quint").ids, "U0ZQ7Y4KD1"
  end

  test "find ranks the exact name first" do
    named!("U0ZQ7Y4KD1", "Mirelle Okontawi")
    named!("U0ZQ7Y4KD2", "Mirelle Okonta")

    assert_equal "U0ZQ7Y4KD2", find_members("mirelle okonta").ids.first
  end

  test "find ranks a prefix match above a contains match" do
    named!("U0ZQ7Y4KD1", "Aquintrella Vorn")
    named!("U0ZQ7Y4KD2", "Zorblax Quintrella")

    ids = find_members("quintrella").ids
    assert_operator ids.index("U0ZQ7Y4KD2"), :<, ids.index("U0ZQ7Y4KD1")
  end

  test "find ranks in-order words at the name start above the same words reversed" do
    named!("U0ZQ7Y4KD1", "Zorblax Quintrell")
    named!("U0ZQ7Y4KD2", "Quintrell Zorblax")
    make_case(subject: "U0ZQ7Y4KD2", opened_at: 2.days.ago)

    assert_equal %w[U0ZQ7Y4KD1 U0ZQ7Y4KD2], find_members("zorblax q").ids
  end

  test "find matches in-order words within one name and not across display name and handle" do
    named!("U0ZQ7Y4KD1", "Zorblax", handle: "quintrellz")
    named!("U0ZQ7Y4KD2", "Zorblax Quintrell")
    make_case(subject: "U0ZQ7Y4KD1", opened_at: 2.days.ago)

    assert_equal %w[U0ZQ7Y4KD2 U0ZQ7Y4KD1], find_members("zorblax q").ids
  end

  test "find and suggest match words under three letters as typed in order" do
    named!("U0ZQ7Y4KD1", "Al Bzorkani")
    named!("U0ZQ7Y4KD2", "Bzork Alvin")
    named!("U0ZQ7Y4KD3", "Achal Bzorkani")

    assert_equal %w[U0ZQ7Y4KD1 U0ZQ7Y4KD3], find_members("al bz").ids
    assert_equal %w[U0ZQ7Y4KD1 U0ZQ7Y4KD3], pick_members("al bz")
  end

  test "find tolerates a typo in a word" do
    named!("U0ZQ7Y4KD1", "Zorblax Quintrell")

    assert_includes find_members("zorblax qiuntrell").ids, "U0ZQ7Y4KD1"
  end

  test "find excludes bots by name and resolves a pasted bot id" do
    named!("U0ZQ7Y4KB1", "Zorblax Quintrell Bot", bot: true)

    assert_not_includes find_members("zorblax quintrell bot").ids, "U0ZQ7Y4KB1"
    assert_equal ["U0ZQ7Y4KB1"], find_members("U0ZQ7Y4KB1").ids
  end

  test "find returns a deleted account by name only after it has a case" do
    named!("U0ZQ7Y4KX1", "Zorblax Gonewald", deleted: true)
    assert_not_includes find_members("gonewald").ids, "U0ZQ7Y4KX1"

    make_case(subject: "U0ZQ7Y4KX1", opened_at: 2.days.ago)
    assert_includes find_members("gonewald").ids, "U0ZQ7Y4KX1"
  end

  test "find ranks a member with a case above one with the same name and no case" do
    named!("U0ZQ7Y4KD1", "Zorblax Twinning")
    named!("U0ZQ7Y4KD2", "Zorblax Twinning")
    make_case(subject: "U0ZQ7Y4KD2", opened_at: 2.days.ago)

    assert_equal "U0ZQ7Y4KD2", find_members("zorblax twinning").ids.first
  end

  test "find ranks a display name match above a real_name only match" do
    named!("U0ZQ7Y4KD1", "Quillon Vex")
    named!("U0ZQ7Y4KD2", "spacecat", real_name: "Quillon Brightwater")
    make_case(subject: "U0ZQ7Y4KD2", opened_at: 2.days.ago)

    ids = find_members("quillon").ids
    assert_operator ids.index("U0ZQ7Y4KD1"), :<, ids.index("U0ZQ7Y4KD2")
  end

  test "find ranks an exact display name above an exact real_name match" do
    named!("U0ZQ7Y4KD1", "lynnzo")
    named!("U0ZQ7Y4KD2", "ghost of lynnzora", real_name: "lynnzo")
    make_case(subject: "U0ZQ7Y4KD2", opened_at: 2.days.ago)

    assert_equal "U0ZQ7Y4KD1", find_members("lynnzo").ids.first
  end

  test "find matches real_name only when an actor is given" do
    named!("U0ZQ7Y4KD1", "tamz", real_name: "Tamsin Okafor-Reyes", email: "tamsin.or@throwaway.example")

    assert_includes find_members("okafor").ids, "U0ZQ7Y4KD1"
    assert_not_includes find_members("okafor", actor: nil).ids, "U0ZQ7Y4KD1"
  end

  test "find with an exact email returns only that member" do
    named!("U0ZQ7Y4KD1", "tamz", email: "tamsin.or@throwaway.example")
    named!("U0ZQ7Y4KD2", "tamsin or", email: "tamsin.or2@throwaway.example")

    assert_equal ["U0ZQ7Y4KD1"], find_members("Tamsin.OR@throwaway.example").ids
  end

  test "find limits ids and total counts every match" do
    3.times { |n| named!("U0ZQ7Y4KV#{n}", "Vexmorran #{n}") }

    result = find_members("vexmorran", limit: 2)
    assert_equal 2, result.ids.size
    assert_equal 3, result.total
  end

  test "find does not raise on punctuation and pattern characters" do
    assert_nothing_raised { find_members("50%_off:x it's") }
    assert_nothing_raised { find_members(":limit :whole ?") }
  end

  test "find returns no ids and a zero total for blank or @ only input" do
    assert_equal [[], 0], find_members("  ").to_a
    assert_equal [[], 0], find_members("@").to_a
  end

  def pick_members(term, **opts)
    Fd::MemberFinder.new(term, actor: @staff).suggest(limit: Fd::Member::LIMIT, **opts)
  end

  test "suggest matches words in any order and ranks an exact name or handle first" do
    named!("U0ZQ7Y4KD1", "Mirelle Okontawi")
    named!("U0ZQ7Y4KD2", "Mirelle Okonta")
    named!("U0ZQ7Y4KD3", "spacecat", handle: "okontawi")

    assert_equal "U0ZQ7Y4KD2", pick_members("mirelle okonta").first
    assert_equal "U0ZQ7Y4KD3", pick_members("okontawi").first
    assert_includes pick_members("okontawi mirelle"), "U0ZQ7Y4KD1"
  end

  test "suggest returns nothing under three letters and resolves a pasted id" do
    named!("U0ZQ7Y4KD1", "Zo Quintrell")

    assert_empty pick_members("zo")
    assert_empty pick_members("@zo")
    assert_equal ["U0ZQ7Y4KD1"], pick_members("<@U0ZQ7Y4KD1>")
    assert_empty pick_members("U0NOBODY99")
  end

  test "suggest excludes deleted accounts and bots by default and resolves a pasted deleted id" do
    named!("U0ZQ7Y4KX1", "Zorblax Gonewald", deleted: true)
    named!("U0ZQ7Y4KB1", "Zorblax Gonewald Bot", bot: true)
    make_case(subject: "U0ZQ7Y4KX1", opened_at: 2.days.ago)

    assert_empty pick_members("gonewald")
    assert_equal ["U0ZQ7Y4KB1"], pick_members("gonewald", bots: true)
    assert_equal ["U0ZQ7Y4KX1"], pick_members("U0ZQ7Y4KX1")
  end

  test "suggest with everyone true orders live members then bots then deleted accounts" do
    named!("U0ZQ7Y4KD1", "Zorblax Quintrell")
    named!("U0ZQ7Y4KX1", "Zorblax Quintrell", deleted: true)
    named!("U0ZQ7Y4KB1", "Zorblax Quintrell", bot: true)

    assert_equal %w[U0ZQ7Y4KD1 U0ZQ7Y4KB1 U0ZQ7Y4KX1], pick_members("zorblax quintrell", everyone: true)
    assert_equal %w[U0ZQ7Y4KD1], pick_members("zorblax quintrell")
  end

  test "suggest with case_id ranks participants first among equal matches only" do
    named!("U0ZQ7Y4KD1", "Zorblax Twinning")
    named!("U0ZQ7Y4KD2", "Zorblax Twinning")
    named!("U0ZQ7Y4KD3", "Zorblax Twinningham")
    kase = make_case(subject: "U0ZQ7Y4KD2", opened_at: 2.days.ago)
    kase.add_subject!("U0ZQ7Y4KD3")

    assert_equal %w[U0ZQ7Y4KD2 U0ZQ7Y4KD1 U0ZQ7Y4KD3], pick_members("zorblax twinning", case_id: kase.id)
    assert_equal %w[U0ZQ7Y4KD1 U0ZQ7Y4KD2 U0ZQ7Y4KD3], pick_members("zorblax twinning")
  end

  test "suggest_sql orders by match_rank then case participation then messages_posted" do
    sql = Fd::MemberFinder.new("zorblax", actor: @staff).suggest_sql(8, case_id: 7)
    order = sql[sql.rindex("ORDER BY")..]

    assert_operator order.index("k.match_rank"), :<, order.index("participant.case_id = 7")
    assert_operator order.index("participant.case_id = 7"), :<, order.index("w.messages_posted DESC")
  end
end

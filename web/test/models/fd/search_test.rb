require "test_helper"

class Fd::SearchTest < ActiveSupport::TestCase
  def build_search(term, **options)
    Fd::Search.new(term, **options)
  end

  def kinds(term)
    build_search(term).groups.map(&:key)
  end

  def rows(term, kind, limit: Fd::Search::LIMIT)
    build_search(term, limit: limit).groups.find { |group| group.key == kind }&.rows.to_a
  end

  def ranked(term)
    rows(term, "member", limit: 50).map { |row| row.record.user_id }
  end

  test "searching? is false for blank or one character term and groups are empty" do
    assert_not_predicate build_search(""), :searching?
    assert_not_predicate build_search(" a "), :searching?
    assert_empty build_search("").groups
  end

  test "groups omit kinds without matches" do
    kase = make_case(opened_at: 2.days.ago)
    Fd::Note.create!(case_id: kase.id, body: "the noisiest one yet", author: "UFF1")

    assert_equal ["note"], kinds("noisiest")
  end

  test "case rows match plain id or case prefix or hash prefix" do
    kase = make_case(opened_at: 2.days.ago)

    [kase.id.to_s, "case #{kase.id}", "##{kase.id}"].each do |input|
      assert_equal [kase.id], rows(input, "case").map { |row| row.record.id }, input
    end
  end

  test "case rows match member_note of a resolved case" do
    kase = make_case(opened_at: 3.days.ago)
    kase.update!(resolved_at: 1.day.ago, resolution: "no_action",
      member_note: "both sides were rude, told them to drop it")

    assert_includes rows("drop it", "case").map { |row| row.record.id }, kase.id
  end

  test "case rows match subject member handle or display name" do
    member = Fd::Member.live.first
    kase = make_case(subject: member.user_id, opened_at: 2.days.ago)

    result = build_search(member.handle.presence || member.display_name)
    assert_includes result.groups.map(&:key), "case"
    assert_includes result.groups.find { |group| group.key == "case" }.rows.map { |row| row.record.id },
      kase.id
  end

  test "note rows match body and exclude deleted notes" do
    kase = make_case(opened_at: 2.days.ago)
    note = Fd::Note.create!(case_id: kase.id, body: "asked them to drop it", author: "UFF1")
    Fd::Note.create!(case_id: kase.id, body: "drop it, again", author: "UFF1",
      deleted_at: Time.current, deleted_by: "UFF1")

    assert_equal [note.id], rows("drop it", "note").map { |row| row.record.id }
  end

  test "report rows match case report body" do
    kase = make_case(opened_at: 2.days.ago)
    report = Fd::CaseReport.create!(case_id: kase.id, is_anonymous: true, source_app: "relay",
      received_at: 1.day.ago, body: "a raid from six day-old accounts")

    assert_equal [report.id], rows("raid", "report").map { |row| row.record.id }
  end

  test "group total counts all matches when rows are capped by limit" do
    kase = make_case(opened_at: 2.days.ago)
    5.times { |n| Fd::Note.create!(case_id: kase.id, body: "raid number #{n}", author: "UFF1") }

    group = build_search("raid", limit: 3).groups.sole
    assert_equal 3, group.rows.size
    assert_equal 5, group.total
    assert_equal 5, build_search("raid").total
  end

  test "text row snippet is windowed around the match with a leading ellipsis" do
    kase = make_case(opened_at: 2.days.ago)
    Fd::Note.create!(case_id: kase.id, author: "UFF1",
      body: "#{'a lot of preamble that nobody needs to read ' * 4}the raid came from six accounts")

    snippet = rows("raid", "note").sole.snippet
    assert_includes snippet, "raid"
    assert snippet.length <= Fd::Search::WINDOW + 2, "snippet length #{snippet.length} exceeds WINDOW"
    assert snippet.start_with?("…"), "snippet cut from the middle starts with ellipsis"
  end

  test "text row snippet equals body when body is short" do
    kase = make_case(opened_at: 2.days.ago)
    Fd::Note.create!(case_id: kase.id, body: "the raid again", author: "UFF1")

    assert_equal "the raid again", rows("raid", "note").sole.snippet
  end

  test "case rows order open before resolved" do
    old = make_case(opened_at: 3.days.ago)
    old.update!(resolved_at: 1.day.ago, resolution: "no_action",
      member_note: "the raid was over by then")
    open = make_case(opened_at: 4.days.ago)
    open.update!(member_note: "the raid is still going")

    ids = rows("raid", "case").map { |row| row.record.id }
    assert_equal [open.id, old.id], ids & [open.id, old.id]
  end

  test "case rows order exact id match first" do
    target_case = make_case(opened_at: 5.days.ago)
    target_case.update!(member_note: "the raid started here")
    make_case(opened_at: 1.hour.ago).update!(member_note: "another raid, newer")

    assert_equal target_case.id, rows(target_case.id.to_s, "case").first.record.id
  end

  test "member rows order member with a case above member without" do
    before = ranked("na")
    clean_member, flagged_member = before.last(2)
    skip "corpus has no two members sharing a name" if clean_member.nil? || clean_member == flagged_member

    make_case(subject: flagged_member, opened_at: 2.days.ago)

    after = ranked("na")
    assert after.index(flagged_member) < after.index(clean_member),
      "member with a case ranks above member without"
  end

  test "at and hash prefixes narrow groups to member and case kinds" do
    member = Fd::Member.live.first
    make_case(subject: member.user_id, opened_at: 2.days.ago)
    name = member.handle.presence || member.display_name

    assert_includes kinds(name), "case"
    assert_equal ["member"], kinds("@#{name}")
    assert_equal ["case"], kinds("##{name}")
  end

  test "bare prefix lists rows for its kind" do
    kase = make_case(subject: Fd::Member.live.first.user_id, opened_at: 2.days.ago)
    Fd::Note.create!(case_id: kase.id, body: "a note about the raid", author: "UFF1")

    assert_equal ["case"], kinds("#")
    assert_equal ["note"], kinds("n:")
    assert_equal ["member"], kinds("@")
    assert rows("#", "case").any?, "bare case scope lists cases"
  end

  test "bare case scope orders open case first" do
    open = make_case(opened_at: 1.hour.ago)
    make_case(opened_at: 30.minutes.ago).update!(resolved_at: Time.current,
      resolution: "no_action")

    assert_equal open.id, rows("#", "case").first.record.id
  end

  test "bare case scope total equals rows size and rows have no snippet" do
    make_case(opened_at: 2.days.ago)
    group = build_search("#").groups.sole

    assert_equal group.rows.size, group.total
    assert_nil group.rows.first.snippet
  end

  test "scope option narrows groups like a prefix" do
    kase = make_case(opened_at: 2.days.ago)
    kase.update!(member_note: "a raid, six accounts")
    Fd::Note.create!(case_id: kase.id, body: "a note about the raid", author: "UFF1")

    assert_equal ["case", "note"], kinds("raid")
    assert_equal ["note"], build_search("raid", scope: "note").groups.map(&:key)
  end

  test "scoped search returns more rows than the default limit" do
    kase = make_case(opened_at: 2.days.ago)
    6.times { |n| Fd::Note.create!(case_id: kase.id, body: "raid #{n}", author: "UFF1") }

    assert_equal 3, rows("raid", "note").size
    assert_equal 6, build_search("raid", scope: "note").groups.sole.rows.size
  end

  test "unknown scope is ignored" do
    Fd::Note.create!(subject_user_id: "USUB", body: "a raid, six accounts", author: "UFF1")

    assert_equal ["note"], build_search("raid", scope: "vibes").groups.map(&:key)
  end

  test "case rows match Slack thread link to case thread" do
    kase = make_case(opened_at: 2.days.ago)
    Fd::CaseThread.create!(case_id: kase.id, channel_id: "C0266FRGV",
      thread_ts: "1754487721.123456", added_by: "UFF1", is_primary: true)

    link = "https://hackclub.slack.com/archives/C0266FRGV/p1754487721123456"
    assert_equal [kase.id], rows(link, "case").map { |row| row.record.id }
  end

  test "Slack thread link without case thread is searching and has no groups" do
    link = "https://hackclub.slack.com/archives/C0NOTHING/p1754487721123456"

    assert_predicate build_search(link), :searching?
    assert_empty build_search(link).groups
  end

  test "groups order member before case" do
    member = Fd::Member.live.first
    make_case(subject: member.user_id, opened_at: 2.days.ago)

    assert_equal ["member", "case"], kinds(member.display_name)
  end
end

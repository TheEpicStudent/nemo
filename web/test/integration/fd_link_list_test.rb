require "test_helper"

class FdLinkListTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    sign_in_as(hold_role!("ULISTBOSS", "community_manager"))
    %w[ULISTA ULISTB ULISTC ULISTD ULISTE].each { |user_id| member!(user_id) }
    link!("ULISTA", "ULISTB", 9.0, '{"mailbox_alias": {"value": "a@b.example", "score": 8.0}}')
    link!("ULISTA", "ULISTC", 6.0, '{"ip_stable": {"value": "81.2.69.144", "score": 5.0}}')
    link!("ULISTA", "ULISTD", 3.5, '{"device_agent": {"value": "agent", "score": 3.0}}')
    link!("ULISTA", "ULISTE", 4.0, '{"ip_stable": {"value": "81.2.69.145", "score": 5.0}}', label: "household")
    a, b = %w[ULISTA ULISTC]
    as_pipeline("INSERT INTO fd.member_link_verdict (a_user_id, b_user_id, verdict, decided_by) VALUES (?, ?, 'household', 'ULISTBOSS')", a, b)
    seeded!("fd.member_link_verdict", "a_user_id", a)
  end

  def link!(one, two, score, signals, label: nil)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal, signals, label) VALUES (?, ?, ?, 'x', ?::jsonb, ?)",
      a, b, score, signals, label)
    seeded!("fd.member_link", "a_user_id", a)
  end

  def sample!(one, two, band)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.link_sample (a_user_id, b_user_id, band, top_signal, score) VALUES (?, ?, ?, 'x', 1)", a, b, band)
    seeded!("fd.link_sample", "a_user_id", a)
  end

  def pairs
    css_select(".link-table tbody tr").map { |row| row.css(".member-face").map { |face| face.text.squish.downcase } }
  end

  test "each band and the labelled and reviewed links have their own view" do
    { "certain" => [%w[ulista ulistb]], "strong" => [%w[ulista ulistc]], "weak" => [%w[ulista ulistd]],
      "labelled" => [%w[ulista uliste]], "reviewed" => [%w[ulista ulistc]] }.each do |view, expected|
      get fd_links_path(view: view)
      assert_equal expected, pairs.map { |pair| pair.map { |face| face.delete_prefix("@") } }, view
    end
  end

  test "the tabs count each view" do
    get fd_links_path(view: "certain")

    counts = css_select("nav.views a.view").to_h { |tab| [tab.children.first.text.squish, tab.at_css(".view-count").text.to_i] }
    assert_equal 1, counts["Certain"]
    assert_equal 1, counts["Strong"]
    assert_equal 1, counts["Reviewed"]
  end

  test "sampled links list the unlabelled ones first and count in their tab" do
    sample!("ULISTA", "ULISTC", "strong")
    sample!("ULISTA", "ULISTD", "weak")

    get fd_links_path(view: "sampled")

    assert_equal [%w[ulista ulistd], %w[ulista ulistc]], pairs.map { |pair| pair.map { |face| face.delete_prefix("@") } }
    counts = css_select("nav.views a.view").to_h { |tab| [tab.children.first.text.squish, tab.at_css(".view-count").text.to_i] }
    assert_equal 2, counts["Sampled"]
  end

  test "the signal filter keeps the links that carry that kind of signal" do
    get fd_links_path(view: "certain", signal: "network")
    assert_select ".link-table", 0
    assert_select ".empty-title", "No links"

    get fd_links_path(view: "certain", signal: "email")
    assert_equal 1, pairs.size
  end

  test "addresses and emails in a signal stay hidden without identity.read" do
    firefighter = hold_role!("ULISTFF", "firefighter")
    move_capability!("firefighter", "identity.read", false, by: "ULISTBOSS")
    sign_in_as(firefighter)

    get fd_links_path(view: "certain")
    assert_no_match "a@b.example", response.body
    get fd_links_path(view: "weak")
    assert_match "agent", response.body
  end
end

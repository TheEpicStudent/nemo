require "test_helper"

class FdLinkListTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    sign_in_as(grant_role!("ULISTBOSS", "community_manager"))
    %w[ULISTA ULISTB ULISTC ULISTD ULISTE ULISTF].each { |user_id| member!(user_id) }
    link!("ULISTA", "ULISTB", 9.0, '{"mailbox_alias": {"value": "a@b.example", "score": 8.0}}')
    link!("ULISTA", "ULISTC", 6.0, '{"ip_stable": {"value": "81.2.69.144", "score": 5.0}}')
    link!("ULISTA", "ULISTD", 3.5, '{"device_agent": {"value": "agent", "score": 3.0}}')
    link!("ULISTA", "ULISTE", 4.0, '{"ip_stable": {"value": "81.2.69.145", "score": 5.0}}', label: "staff_test")
    link!("ULISTA", "ULISTF", 6.5, '{"ip_stable": {"value": "81.2.69.146", "score": 5.0}}')
    a, b = %w[ULISTA ULISTC]
    as_pipeline("INSERT INTO fd.member_link_verdict (a_user_id, b_user_id, verdict, decided_by) VALUES (?, ?, 'different_people', 'ULISTBOSS')", a, b)
    seeded!("fd.member_link_verdict", "a_user_id", a)
  end

  def link!(one, two, score, signals, label: nil)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link (a_user_id, b_user_id, score, top_signal, signals, label) VALUES (?, ?, ?, 'x', ?::jsonb, ?)",
      a, b, score, signals, label)
    seeded!("fd.member_link", "a_user_id", a)
  end

  def sample!(one, two, band, variant: "live")
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.link_sample (variant, a_user_id, b_user_id, band, top_signal, score) VALUES (?, ?, ?, ?, 'x', 1)",
      variant, a, b, band)
    seeded!("fd.link_sample", "a_user_id", a)
  end

  def shadow_link!(variant, one, two, score)
    a, b = [one, two].sort
    as_pipeline("INSERT INTO fd.member_link_shadow (variant, a_user_id, b_user_id, score, top_signal, signals) " \
                "VALUES (?, ?, ?, ?, 'mailbox_alias', '{\"mailbox_alias\": {\"value\": \"a@b.example\", \"score\": 8.0}}'::jsonb)",
      variant, a, b, score)
    seeded!("fd.member_link_shadow", "a_user_id", a)
  end

  def pairs
    css_select(".link-table tbody tr").map { |row| row.css(".member-face").map { |face| face.text.squish.downcase } }
  end

  test "links index renders one view per band labelled and reviewed" do
    { "certain" => [%w[ulista ulistb]], "strong" => [%w[ulista ulistf]], "weak" => [%w[ulista ulistd]],
      "labelled" => [%w[ulista uliste]], "reviewed" => [%w[ulista ulistc]] }.each do |view, expected|
      get fd_links_path(view: view)
      assert_equal expected, pairs.map { |pair| pair.map { |face| face.delete_prefix("@") } }, view
    end
  end

  test "links index omits a reviewed pair from its band and lists it under reviewed" do
    get fd_links_path(view: "strong")
    refute_includes pairs.flatten, "ulistc"

    get fd_links_path(view: "reviewed")
    assert_includes pairs.flatten, "ulistc"
  end

  test "links index paginates a band larger than the page size" do
    105.times do |n|
      user_id = "UPAGE#{n.to_s.rjust(3, '0')}"
      member!(user_id)
      link!("ULISTA", user_id, 10.0, '{"ip_stable": {"value": "81.2.69.200", "score": 5.0}}')
    end

    get fd_links_path(view: "certain")
    assert_equal 100, pairs.size
    assert_select ".pager-at", "Page 1 of 2"

    get fd_links_path(view: "certain", page: 2)
    assert_equal 6, pairs.size
    assert_select ".pager-at", "Page 2 of 2"
    assert_select "turbo-frame#member-links-list[data-src=?]", fd_links_path(view: "certain", page: 2)
  end

  test "links index tab counts match each view" do
    get fd_links_path(view: "certain")

    counts = css_select("nav.views a.view").to_h { |tab| [tab.children.first.text.squish, tab.at_css(".view-count").text.to_i] }
    assert_equal 1, counts["Certain"]
    assert_equal 1, counts["Strong"]
    assert_equal 1, counts["Reviewed"]
  end

  test "sampled view orders links without a verdict first and counts them" do
    sample!("ULISTA", "ULISTC", "strong")
    sample!("ULISTA", "ULISTD", "weak")

    get fd_links_path(view: "sampled")

    assert_equal [%w[ulista ulistd], %w[ulista ulistc]], pairs.map { |pair| pair.map { |face| face.delete_prefix("@") } }
    counts = css_select("nav.views a.view").to_h { |tab| [tab.children.first.text.squish, tab.at_css(".view-count").text.to_i] }
    assert_equal 2, counts["Sampled"]
  end

  test "sampled view with variant lists shadow links and shows the Set filter" do
    sample!("ULISTA", "ULISTC", "strong")
    shadow_link!("flat_inbox", "ULISTC", "ULISTD", 8.0)
    sample!("ULISTC", "ULISTD", "certain", variant: "flat_inbox")

    get fd_links_path(view: "sampled")
    assert_select ".filter-key", text: "Set"
    assert_equal [%w[ulista ulistc]], pairs.map { |pair| pair.map { |face| face.delete_prefix("@") } }

    get fd_links_path(view: "sampled", variant: "flat_inbox")
    assert_equal [%w[ulistc ulistd]], pairs.map { |pair| pair.map { |face| face.delete_prefix("@") } }
    assert_select ".filter-val", text: "flat_inbox"
    counts = css_select("nav.views a.view").to_h { |tab| [tab.children.first.text.squish, tab.at_css(".view-count").text.to_i] }
    assert_equal 1, counts["Sampled"]
    assert_equal 1, counts["Certain"]

    get fd_links_path(view: "sampled", variant: "nope")
    assert_equal [%w[ulista ulistc]], pairs.map { |pair| pair.map { |face| face.delete_prefix("@") } }
  end

  test "sampled view with only live samples hides the Set filter" do
    sample!("ULISTA", "ULISTC", "strong")

    get fd_links_path(view: "sampled")

    assert_select ".filter-key", text: "Set", count: 0
  end

  test "links index signal filter lists only links with that signal kind" do
    get fd_links_path(view: "certain", signal: "network")
    assert_select ".link-table", 0
    assert_select ".empty-title", "No links"

    get fd_links_path(view: "certain", signal: "email")
    assert_equal 1, pairs.size
  end

  test "links index hides addresses and emails without identity.read" do
    firefighter = grant_role!("ULISTFF", "firefighter")
    override_capability!("firefighter", "identity.read", false, by: "ULISTBOSS")
    sign_in_as(firefighter)

    get fd_links_path(view: "certain")
    assert_no_match "a@b.example", response.body
    get fd_links_path(view: "weak")
    assert_match "agent", response.body
  end
end

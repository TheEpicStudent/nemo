require "test_helper"

class FdThrowawayDomainTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  RING = "UTHROW1".freeze
  PLAIN = "UTHROW2".freeze

  setup do
    @manager = hold_role!("UTHROWBOSS", "community_manager")
    member!(RING, email: "kid42@e.izie.top")
    member!(PLAIN, email: "kid@gmail.com")
    as_pipeline("INSERT INTO fd.throwaway_domain (domain, source) VALUES ('e.izie.top', 'curated') ON CONFLICT DO NOTHING")
    seeded!("fd.throwaway_domain", "domain", "e.izie.top")
  end

  def email_fact
    css_select(".member-facts .fact").find { |one| one.at("dt").text.strip == "Email" }
  end

  test "an email on a throwaway domain is marked beside the address" do
    sign_in_as(@manager)

    get fd_member_path(RING)
    assert_match "kid42@e.izie.top", email_fact.text
    assert_match "Throwaway domain", email_fact.text

    get fd_member_path(PLAIN)
    assert_no_match "Throwaway domain", email_fact.text
  end

  test "the mark stays hidden with the address from those who cannot read identities" do
    firefighter = hold_role!("UTHROWFF", "firefighter")
    move_capability!("firefighter", "identity.read", false, by: "UTHROWBOSS")
    sign_in_as(firefighter)

    get fd_member_path(RING)
    assert_no_match "e.izie.top", response.body
    assert_no_match "Throwaway domain", response.body
  end

  test "the domain is read from the address in lower case" do
    assert_equal "e.izie.top", Fd::ThrowawayDomain.domain_of(" Kid@E.Izie.Top ")
    assert_nil Fd::ThrowawayDomain.domain_of("no-at-sign")
    assert Fd::ThrowawayDomain.listed?("x@E.IZIE.TOP")
    assert_not Fd::ThrowawayDomain.listed?(nil)
  end
end

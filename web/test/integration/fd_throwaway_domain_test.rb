require "test_helper"

class FdThrowawayDomainTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  THROWAWAY = "UTHROW1".freeze
  REGULAR = "UTHROW2".freeze

  setup do
    @manager = grant_role!("UTHROWBOSS", "community_manager")
    member!(THROWAWAY, email: "kid42@e.izie.top")
    member!(REGULAR, email: "kid@gmail.com")
    as_pipeline("INSERT INTO fd.throwaway_domain (domain, source) VALUES ('e.izie.top', 'curated') ON CONFLICT DO NOTHING")
    seeded!("fd.throwaway_domain", "domain", "e.izie.top")
  end

  def email_fact
    css_select(".member-facts .fact").find { |fact| fact.at("dt").text.strip == "Email" }
  end

  test "member show marks email on a throwaway domain" do
    sign_in_as(@manager)

    get fd_member_path(THROWAWAY)
    assert_match "kid42@e.izie.top", email_fact.text
    assert_match "Throwaway domain", email_fact.text

    get fd_member_path(REGULAR)
    assert_no_match "Throwaway domain", email_fact.text
  end

  test "member show without identity.read hides email and throwaway mark" do
    firefighter = grant_role!("UTHROWFF", "firefighter")
    override_capability!("firefighter", "identity.read", false, by: "UTHROWBOSS")
    sign_in_as(firefighter)

    get fd_member_path(THROWAWAY)
    assert_no_match "e.izie.top", response.body
    assert_no_match "Throwaway domain", response.body
  end

  test "domain_of strips and downcases address and listed? ignores case" do
    assert_equal "e.izie.top", Fd::ThrowawayDomain.domain_of(" Kid@E.Izie.Top ")
    assert_nil Fd::ThrowawayDomain.domain_of("no-at-sign")
    assert Fd::ThrowawayDomain.listed?("x@E.IZIE.TOP")
    assert_not Fd::ThrowawayDomain.listed?(nil)
  end
end

require "test_helper"

class FdBlockedDomainsTest < ActionDispatch::IntegrationTest
  include SeedsPipelineTables

  setup do
    @me = grant_role!("UME", "community_manager")
    sign_in_as(@me)
  end

  def add(**params)
    post fd_blocked_domains_path, params: { domain: "throwaway.example" }.merge(params)
  end

  def member_on!(user_id, email)
    member!(user_id, email: email)
  end

  test "create adds an active domain with flag effect and exact match mode" do
    add

    one = Fd::BlockedDomain.active.last
    assert_equal "throwaway.example", one.domain
    assert_equal Fd::BlockedDomain::FLAG, one.effect, "default effect is flag"
    assert_equal Fd::BlockedDomain::EXACT, one.match_mode
  end

  test "create strips the at sign and lowercases the domain" do
    add(domain: "  @Throwaway.Example  ")

    assert_equal "throwaway.example", Fd::BlockedDomain.active.last.domain
  end

  test "create with an invalid domain adds no row and alerts" do
    assert_no_difference -> { Fd::BlockedDomain.count } do
      add(domain: "localhost")
    end
    assert_match(/not a domain/, flash[:alert])

    assert_no_difference -> { Fd::BlockedDomain.count } do
      add(domain: "")
    end
  end

  test "create with a domain on 30 accounts is refused unless anyway is set" do
    30.times { |n| member_on!("USCHOOL#{n}", "kid#{n}@school.example") }

    assert_no_difference -> { Fd::BlockedDomain.count } do
      add(domain: "school.example")
    end
    assert_equal "domain", flash[:field_error]["field"]
    assert_match(/is on 30 accounts already/, flash[:field_error]["message"])
    assert_equal "school.example", flash[:field_error]["was"]

    assert_difference -> { Fd::BlockedDomain.count }, 1 do
      add(domain: "school.example", anyway: "1")
    end
  end

  test "domains tab renders the anyway input only after a refusal" do
    get fd_configuration_path(tab: "domains")
    assert_select %(input[name="anyway"]), false, "no anyway input before a refusal"

    30.times { |n| member_on!("USCHOOL#{n}", "kid#{n}@school.example") }
    add(domain: "school.example")
    follow_redirect!

    assert_select %(input[name="anyway"])
    assert_select ".field-wrong", /is on 30 accounts already/
    assert_select %(input[name="domain"][value="school.example"])
  end

  test "create with a domain on 10 accounts adds one row" do
    10.times { |n| member_on!("UPLAIN#{n}", "kid#{n}@school.example") }

    assert_difference -> { Fd::BlockedDomain.count }, 1 do
      add(domain: "throwaway.example")
    end
  end

  test "create with deactivate effect without member.deactivate adds no row" do
    Authz::Override.create!(role: "firefighter", capability: "member.deactivate",
      allowed: false, changed_by: "UME")
    sign_in_as(grant_role!("UFF", "firefighter"))

    assert_no_difference -> { Fd::BlockedDomain.count } do
      add(effect: "deactivate")
    end
  end

  test "create with an already active domain adds no row and alerts" do
    add
    assert_no_difference -> { Fd::BlockedDomain.active.count } do
      add
    end
    assert_match(/Already on the list/, flash[:alert])
  end

  test "destroy retires the domain and sets retired_by and retired_at" do
    add
    one = Fd::BlockedDomain.active.last

    delete fd_blocked_domain_path(one)

    assert_not one.reload.active
    assert_equal "UME", one.retired_by
    assert_not_nil one.retired_at
  end

  test "create and destroy write two blocked_domain audit entries" do
    assert_difference -> { Fd::AuditEntry.where(entity_type: "blocked_domain").count }, 2 do
      add
      delete fd_blocked_domain_path(Fd::BlockedDomain.active.last)
    end
  end

  test "exact mode matches only the domain and suffix mode also matches subdomains" do
    exact = Fd::BlockedDomain.add!(domain: "throwaway.example", by: "UME")
    assert exact.matches?("throwaway.example")
    assert_not exact.matches?("mail.throwaway.example")

    wide = Fd::BlockedDomain.add!(domain: "throwaway.example", by: "UME",
      match_mode: Fd::BlockedDomain::SUFFIX)
    assert wide.matches?("mail.throwaway.example")
    assert_not wide.matches?("notthrowaway.example")
  end

  test "strictest_for returns deactivate over flag when two entries match" do
    Fd::BlockedDomain.add!(domain: "throwaway.example", by: "UME", effect: "flag")
    Fd::BlockedDomain.add!(domain: "throwaway.example", by: "UME",
      match_mode: "suffix", effect: "deactivate")

    assert_equal "deactivate", Fd::BlockedDomain.strictest_for("throwaway.example").effect
  end

  test "domains tab renders the domain and two data tables" do
    add
    as_pipeline("INSERT INTO fd.join_screen (user_id, email_domain, outcome) " \
                "VALUES (?, ?, 'flagged')", "UCAUGHT", "throwaway.example")
    seeded!("fd.join_screen", "user_id", "UCAUGHT")

    get fd_configuration_path(tab: "domains")
    assert_response :success
    assert_match "throwaway.example", response.body
    assert_select ".data-table", minimum: 2
  end
end

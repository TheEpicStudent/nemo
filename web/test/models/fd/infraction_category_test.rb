require "test_helper"

module Fd
  class InfractionCategoryTest < ActiveSupport::TestCase
    setup { Current.categories = nil }

    test "the table holds the twenty-two categories in order" do
      assert_equal 22, InfractionCategory.active_keys.size
      assert_equal "nos", InfractionCategory.active_keys.first
      assert_equal "Spam, mass pings or invites", InfractionCategory.label("spam")
      assert_equal "Disruption or trolling", InfractionCategory.label("disruption")
    end

    test "a retired category keeps its label but leaves the pickers" do
      InfractionCategory.find("adult").update!(retired_at: Time.current)
      Current.categories = nil

      assert_equal "Adult", InfractionCategory.label("adult")
      assert InfractionCategory.known_key?("adult")
      assert_not InfractionCategory.active_key?("adult")
      assert_not_includes InfractionCategory.active_keys, "adult"
    end

    test "an unknown key reads as itself" do
      assert_equal "brand new", InfractionCategory.label("brand_new")
      assert_not InfractionCategory.known_key?("brand_new")
    end

    test "case labels come from the table" do
      assert_equal "Impersonation", Case.category_label("impersonation")
    end
  end
end

require "test_helper"

module Fd
  class InfractionCategoryTest < ActiveSupport::TestCase
    setup { Current.categories = nil }

    test "active_keys returns 22 keys starting with nos and label resolves from the table" do
      assert_equal 22, InfractionCategory.active_keys.size
      assert_equal "nos", InfractionCategory.active_keys.first
      assert_equal "Spam, mass pings or invites", InfractionCategory.label("spam")
      assert_equal "Disruption or trolling", InfractionCategory.label("disruption")
    end

    test "retired category keeps label and known_key? and leaves active_keys" do
      InfractionCategory.find("adult").update!(retired_at: Time.current)
      Current.categories = nil

      assert_equal "Adult", InfractionCategory.label("adult")
      assert InfractionCategory.known_key?("adult")
      assert_not InfractionCategory.active_key?("adult")
      assert_not_includes InfractionCategory.active_keys, "adult"
    end

    test "label humanizes an unknown key and known_key? is false" do
      assert_equal "brand new", InfractionCategory.label("brand_new")
      assert_not InfractionCategory.known_key?("brand_new")
    end

    test "Case.category_label returns the InfractionCategory label" do
      assert_equal "Impersonation", Case.category_label("impersonation")
    end
  end
end

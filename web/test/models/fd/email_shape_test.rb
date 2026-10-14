require "test_helper"

class Fd::EmailShapeTest < ActiveSupport::TestCase
  test "a whole string is an address when it has one at sign and a dotted domain" do
    assert Fd::EmailShape.full?("kid@alts.example")
    assert Fd::EmailShape.full?("a@b.c")
    assert_not Fd::EmailShape.full?("kid@alts")
    assert_not Fd::EmailShape.full?("kid@.example")
    assert_not Fd::EmailShape.full?("kid@@alts.example")
    assert_not Fd::EmailShape.full?("two words@alts.example")
    assert_not Fd::EmailShape.full?("@alts.example")
  end

  test "an address ends in letters" do
    assert Fd::EmailShape.address?("kid@alts.example")
    assert_not Fd::EmailShape.address?("kid@alts.123")
    assert_not Fd::EmailShape.address?("kid@alts.")
  end

  test "an address is found inside other text" do
    assert Fd::EmailShape.within?("mail kid@alts.example please")
    assert Fd::EmailShape.within?(%(from:"kid@alts.example"))
    assert_not Fd::EmailShape.within?("kid at alts dot example")
    assert_not Fd::EmailShape.within?("plain words")
  end

  test "long runs without an address answer quickly" do
    started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    [".", "a", "@", "a@"].each do |unit|
      text = unit * 50_000
      Fd::EmailShape.full?(text)
      Fd::EmailShape.address?(text)
      Fd::EmailShape.within?(text)
    end

    assert_operator Process.clock_gettime(Process::CLOCK_MONOTONIC) - started, :<, 2
  end
end

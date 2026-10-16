require "test_helper"

class Fd::EmailShapeTest < ActiveSupport::TestCase
  test "full? requires one at sign and a dotted domain" do
    assert Fd::EmailShape.full?("kid@alts.example")
    assert Fd::EmailShape.full?("a@b.c")
    assert_not Fd::EmailShape.full?("kid@alts")
    assert_not Fd::EmailShape.full?("kid@.example")
    assert_not Fd::EmailShape.full?("kid@@alts.example")
    assert_not Fd::EmailShape.full?("two words@alts.example")
    assert_not Fd::EmailShape.full?("@alts.example")
  end

  test "address? requires the domain to end in letters" do
    assert Fd::EmailShape.address?("kid@alts.example")
    assert_not Fd::EmailShape.address?("kid@alts.123")
    assert_not Fd::EmailShape.address?("kid@alts.")
  end

  test "within? finds an address inside other text" do
    assert Fd::EmailShape.within?("mail kid@alts.example please")
    assert Fd::EmailShape.within?(%(from:"kid@alts.example"))
    assert_not Fd::EmailShape.within?("kid at alts dot example")
    assert_not Fd::EmailShape.within?("plain words")
  end

  test "full? address? and within? finish quickly on long input" do
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

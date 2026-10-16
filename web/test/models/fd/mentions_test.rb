require "test_helper"

class Fd::MentionsTest < ActiveSupport::TestCase
  test "normalise converts an @id to slack mention form" do
    assert_equal "spoke to <@U08K3F2QX> in DM",
      Fd::Mentions.normalise("spoke to @U08K3F2QX in DM")
  end

  test "normalise converts a bare id to slack mention form" do
    assert_equal "<@U08K3F2QX> started it", Fd::Mentions.normalise("U08K3F2QX started it")
  end

  test "normalise leaves slack mention form unchanged" do
    normalised = "spoke to <@U08K3F2QX> in DM"
    assert_equal normalised, Fd::Mentions.normalise(normalised)
  end

  test "normalise converts every mention in the text" do
    assert_equal "<@U08K3F2QX> and <@W01ABCDEF> were both there",
      Fd::Mentions.normalise("@U08K3F2QX and @W01ABCDEF were both there")
  end

  test "normalise leaves uppercase words that are not ids unchanged" do
    %w[URGENT UPSET WONT UPPERCASE UNDERSTOOD].each do |word|
      assert_equal word, Fd::Mentions.normalise(word), "#{word} is a word, not a member"
    end
  end

  test "normalise leaves an email address unchanged" do
    text = "wrote from UPPERCASE@example.invalid"
    assert_equal text, Fd::Mentions.normalise(text)
  end

  test "ids returns unique mention ids in order" do
    text = "<@U08K3F2QX> and <@W01ABCDEF> and <@U08K3F2QX> again"
    assert_equal %w[U08K3F2QX W01ABCDEF], Fd::Mentions.ids(text)
  end

  test "normalise and ids return empty results for blank input and text without mentions" do
    assert_equal "", Fd::Mentions.normalise("")
    assert_nil Fd::Mentions.normalise(nil)
    assert_empty Fd::Mentions.ids(nil)
    assert_empty Fd::Mentions.ids("no mentions here")
  end

  test "split returns text and mention segments in order" do
    assert_equal ["spoke to ", "<@U08K3F2QX>", " in DM"],
      Fd::Mentions.split("spoke to <@U08K3F2QX> in DM")
  end
end

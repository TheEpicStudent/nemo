require "test_helper"

class Slack::MrkdwnTest < ActiveSupport::TestCase
  def parts(text)
    Slack::Mrkdwn.blocks(text).first["elements"]
  end

  def inline(text)
    parts(text).first["elements"]
  end

  test "blocks returns an empty array for blank input" do
    assert_equal [], Slack::Mrkdwn.blocks("")
    assert_equal [], Slack::Mrkdwn.blocks(nil)
    assert_equal [], Slack::Mrkdwn.blocks("   \n  ")
  end

  test "blocks maps bold italic strike and code delimiters to styles" do
    assert_equal({ "bold" => true }, inline("*loud*").first["style"])
    assert_equal({ "italic" => true }, inline("_soft_").first["style"])
    assert_equal({ "strike" => true }, inline("~gone~").first["style"])
    assert_equal({ "code" => true }, inline("`puts`").first["style"])
  end

  test "blocks applies nested delimiters as combined styles" do
    element = inline("*_both_*").first

    assert_equal "both", element["text"]
    assert_equal({ "bold" => true, "italic" => true }, element["style"])
  end

  test "blocks leaves delimiters surrounded by spaces as text" do
    assert_equal [{ "type" => "text", "text" => "2 * 3 * 4" }], inline("2 * 3 * 4")
  end

  test "blocks maps mentions and channels to user and channel elements with ids" do
    assert_equal({ "type" => "user", "user_id" => "U08EMT46G3V" }, inline("<@U08EMT46G3V>").first)
    assert_equal({ "type" => "channel", "channel_id" => "C0BSBP62C3U" },
      inline("<#C0BSBP62C3U|not-fire-dept>").first)
  end

  test "blocks maps a labelled link and a bare link to link elements" do
    labelled_link = inline("<https://hack.club|the club>").first
    assert_equal({ "type" => "link", "url" => "https://hack.club", "text" => "the club" }, labelled_link)

    assert_equal({ "type" => "link", "url" => "https://hack.club" },
      inline("https://hack.club").first)
  end

  test "blocks maps an emoji to an emoji element with its name" do
    assert_equal({ "type" => "emoji", "name" => "sho" }, inline("hi :sho:").last)
  end

  test "blocks unescapes gt amp and lt entities" do
    assert_equal "a > b & c < d", inline("a &gt; b &amp; c &lt; d").first["text"]
  end

  test "blocks groups consecutive quoted lines into one rich_text_quote" do
    elements = parts("&gt; they said\n&gt; and then\nmine")

    assert_equal "rich_text_quote", elements.first["type"]
    assert_equal "they said\nand then", elements.first["elements"].first["text"]
    assert_equal "rich_text_section", elements.last["type"]
  end

  test "blocks maps a code fence to rich_text_preformatted with literal text" do
    elements = parts("look:\n```\n*not bold*\n```")

    assert_equal "rich_text_preformatted", elements.last["type"]
    assert_equal "*not bold*", elements.last["elements"].first["text"]
  end

  test "blocks does not parse styles inside inline code" do
    element = inline("`*raw*`").first

    assert_equal "*raw*", element["text"]
    assert_equal({ "code" => true }, element["style"])
  end
end

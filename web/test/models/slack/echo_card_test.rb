require "test_helper"

class Slack::EchoCardTest < ActiveSupport::TestCase
  BLOCKS = [
    { "type" => "header", "text" => { "type" => "plain_text",
      "text" => "Channel ban from #general until 10 Mar" } },
    { "type" => "context", "elements" => [{ "type" => "mrkdwn",
      "text" => "Against <@USUB> · logged by <@UME>" }] },
    { "type" => "divider" },
    { "type" => "section", "text" => { "type" => "mrkdwn",
      "text" => "> kept posting spam links after being warned twice" } },
    { "type" => "context", "elements" => [{ "type" => "mrkdwn",
      "text" => "*How it was solved:* they stopped once the ban kicked in" }] }
  ].freeze

  test "echo? is false for a rich_text block" do
    assert_not Slack::EchoCard.echo?([
      { "type" => "rich_text", "elements" => [] }
    ])
  end

  test "echo? is true for a header or context or section block" do
    assert Slack::EchoCard.echo?([{ "type" => "header" }])
    assert Slack::EchoCard.echo?([{ "type" => "context" }])
    assert Slack::EchoCard.echo?([{ "type" => "section" }])
  end

  test "echo? is false for nil and an empty array" do
    assert_not Slack::EchoCard.echo?(nil)
    assert_not Slack::EchoCard.echo?([])
  end

  test "render turns the header block into an echo-head paragraph" do
    html = Slack::EchoCard.render(BLOCKS)
    assert_match %r{<p class="echo-head">Channel ban from #general until 10 Mar</p>}, html
  end

  test "render emits no richtext-rule for a divider block" do
    html = Slack::EchoCard.render(BLOCKS)
    assert_no_match(/richtext-rule/, html)
  end

  test "render outputs context blocks as echo-meta with resolved mention names" do
    html = Slack::EchoCard.render(BLOCKS, names: { "USUB" => "subby", "UME" => "mod" })
    assert_match %r{echo-meta.*Against.*subby.*logged by.*mod}m, html
  end

  test "render turns a quoted section into a richtext-quote blockquote" do
    html = Slack::EchoCard.render(BLOCKS)
    assert_match(
      %r{<blockquote class="richtext-quote">kept posting spam links after being warned twice</blockquote>},
      html,
    )
    assert_no_match(/&gt;/, html)
  end

  test "render keeps the bold How it was solved lead as strong" do
    html = Slack::EchoCard.render(BLOCKS)
    assert_match %r{<strong>How it was solved:</strong> they stopped}, html
  end
end

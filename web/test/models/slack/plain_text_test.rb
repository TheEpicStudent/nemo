require "test_helper"

class Slack::PlainTextTest < ActiveSupport::TestCase
  def plain(text, **lookups)
    Slack::PlainText.for(Slack::Mrkdwn.blocks(text), **lookups)
  end

  test "for with known mentions returns user channel and usergroup names" do
    assert_equal "@pat in #lounge cc @fire-department",
      plain("<@U0123ABCD> in <#C0123ABCD> cc <!subteam^S0123ABCD>", names: { "U0123ABCD" => "pat" },
        channels: { "C0123ABCD" => "lounge" }, usergroups: { "S0123ABCD" => "fire-department" })
  end

  test "for with unknown mentions returns their ids" do
    assert_equal "@U0123ABCD in #C0123ABCD cc @S0123ABCD",
      plain("<@U0123ABCD> in <#C0123ABCD> cc <!subteam^S0123ABCD>")
  end

  test "for with entities quotes and code returns plain characters without markers" do
    assert_equal "they said nobody asked & kept going !report and block code",
      plain("they said\n&gt; nobody asked &amp; kept going\n`!report` and ```block code```")
  end

  test "for with emoji shortcodes returns unicode for standard names and keeps custom names" do
    assert_equal "💀 :sho: 👋🏼", plain(":skull: :sho: :wave::skin-tone-3:")
  end

  test "for with links returns the label or the url" do
    assert_equal "look here https://slack.com/x",
      plain("<https://slack.com/x|look here> <https://slack.com/x>")
  end
end

require "test_helper"

class FdConfigurationTest < ActionDispatch::IntegrationTest
  setup do
    @me = grant_role!("UME", "firefighter")
    sign_in_as(@me)
  end

  def automod_word!(**over)
    Fd::AutomodWord.create!({
      word: "badword", match_mode: "word", effect: "flag", added_by: "UMOD"
    }.merge(over))
  end

  def add(**params)
    post fd_automod_words_path, params: { word: "badword" }.merge(params)
  end

  def live = Fd::AutomodWord.active

  test "show configuration for firefighter renders Automod" do
    get fd_configuration_path
    assert_response :success
    assert_match(/Automod/, response.body)
  end

  test "show configuration renders sidebar link to /fd/configuration" do
    get fd_configuration_path
    assert_match(%r{href="/fd/configuration"}, response.body)
  end

  test "show configuration for community_manager responds success" do
    revoke_roles!("UME")
    grant_role!("UME", "community_manager")
    get fd_configuration_path

    assert_response :success
  end

  test "show configuration for gardener redirects" do
    revoke_roles!("UME")
    grant_role!("UME", "gardener")
    get fd_configuration_path

    assert_response :redirect
  end

  test "create automod word stores normalized attributes and one added audit entry" do
    add(word: "  slur  ", category_key: "harassment_general")
    word = live.sole

    assert_equal "slur", word.word
    assert_equal "word", word.match_mode
    assert_equal "flag", word.effect
    assert_equal "harassment_general", word.category_key
    assert_equal "UME", word.added_by
    assert_equal 1, Fd::AuditEntry.where(entity_type: "automod_word", verb: "added").count
  end

  test "create automod word with blank word alerts and stores nothing" do
    add(word: "   ")

    assert_equal 0, live.count
    assert_match(/Enter a word/, flash[:alert])
  end

  test "create automod word twice stores one row and alerts" do
    add
    add

    assert_equal 1, live.count
    assert_match(/Already on the list/, flash[:alert])
  end

  test "create automod word with invalid regex alerts and stores nothing" do
    add(word: "([a-z", match_mode: "regex")

    assert_equal 0, live.count
    assert_match(/Invalid regex/, flash[:alert])
  end

  test "create automod word with valid regex stores match_mode regex" do
    add(word: "ba+dword", match_mode: "regex")

    assert_equal "regex", live.sole.match_mode
  end

  test "create automod word with unsupported effect stores flag" do
    add(effect: "delete")

    assert_equal "flag", live.sole.effect
  end

  test "create automod word with unknown match_mode stores word" do
    add(match_mode: "sideways")

    assert_equal "word", live.sole.match_mode
  end

  test "create automod word with unknown category_key stores nil" do
    add(category_key: "not_a_category")

    assert_nil live.sole.category_key
  end

  test "destroy automod word sets retired fields and writes one removed audit entry" do
    word = automod_word!
    delete fd_automod_word_path(word)

    assert_equal 0, live.count
    assert_equal "UME", word.reload.retired_by
    assert_not_nil word.retired_at
    assert_equal 1, Fd::AuditEntry.where(entity_type: "automod_word", verb: "removed").count
  end

  test "destroy automod word twice alerts not on the list" do
    word = automod_word!
    delete fd_automod_word_path(word)
    delete fd_automod_word_path(word)

    assert_match(/Not on the list/, flash[:alert])
  end

  test "create automod word after retiring the same word stores a second row" do
    word = automod_word!
    delete fd_automod_word_path(word)
    add(word: "badword")

    assert_equal 1, live.count
    assert_equal 2, Fd::AutomodWord.count
  end

  test "show configuration renders words in a masked element" do
    automod_word!
    get fd_configuration_path

    assert_select %(.masked), /badword/
  end

  test "show configuration renders automod match body and user_id" do
    word = automod_word!
    Fd::AutomodMatch.create!(word_id: word.id, word: word.word, effect: "flag",
      user_id: "USUB", channel_id: "C0266FRGV", message_ts: "1700000000.000100",
      body: "the message that matched")
    get fd_configuration_path

    assert_match(/the message that matched/, response.body)
    assert_match(/USUB/, response.body)
  end

  test "show configuration links match channel to the permalink" do
    word = automod_word!
    Fd::AutomodMatch.create!(word_id: word.id, word: word.word, effect: "flag",
      user_id: "USUB", channel_id: "C0266FRGV", message_ts: "1700000000.000100",
      body: "the message that matched",
      permalink: "https://hackclub.slack.com/archives/C0266FRGV/p1700000000000100")
    get fd_configuration_path

    assert_select %(a.handle[href=?]),
      "https://hackclub.slack.com/archives/C0266FRGV/p1700000000000100"
  end

  test "show configuration links match without permalink to a URL with channel_id" do
    word = automod_word!
    Fd::AutomodMatch.create!(word_id: word.id, word: word.word, effect: "flag",
      user_id: "USUB", channel_id: "C0266FRGV", message_ts: "1700000000.000100",
      body: "the message that matched")
    get fd_configuration_path

    assert_select %(a.handle[href*=?]), "C0266FRGV"
  end

  test "create automod word for gardener stores nothing" do
    revoke_roles!("UME")
    grant_role!("UME", "gardener")
    add

    assert_equal 0, live.count
  end
end

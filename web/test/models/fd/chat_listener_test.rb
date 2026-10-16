require "test_helper"

class Fd::ChatListenerTest < ActiveSupport::TestCase
  test "case_id_from parses a numeric payload as an integer" do
    assert_equal 2633, Fd::ChatListener.case_id_from("2633")
  end

  test "case_id_from returns nil for non numeric empty and nil payloads" do
    assert_nil Fd::ChatListener.case_id_from("case 2633")
    assert_nil Fd::ChatListener.case_id_from("")
    assert_nil Fd::ChatListener.case_id_from(nil)
  end

  test "enabled? is false in the test environment" do
    assert_not Fd::ChatListener.enabled?
  end

  test "serving? is false outside a server process" do
    assert_not Fd::ChatListener.serving?
  end

  test "enabled? is false for falsey NEMO_STREAM values" do
    %w[0 false no off FALSE Off].each do |value|
      with_env("NEMO_STREAM", value) do
        assert_not Fd::ChatListener.enabled?, "NEMO_STREAM=#{value} should not stream"
      end
    end
  end

  test "enabled? is true for truthy NEMO_STREAM values" do
    %w[1 true yes on].each do |value|
      with_env("NEMO_STREAM", value) do
        assert Fd::ChatListener.enabled?, "NEMO_STREAM=#{value} should stream"
      end
    end
  end

  test "enabled? with empty NEMO_STREAM equals serving?" do
    with_env("NEMO_STREAM", "") do
      assert_equal Fd::ChatListener.serving?, Fd::ChatListener.enabled?
    end
  end

  def with_env(name, value)
    original_value, had_key, original_env = ENV[name], ENV.key?(name), Rails.env
    ENV[name] = value
    Rails.env = "production"
    yield
  ensure
    Rails.env = original_env
    had_key ? ENV[name] = original_value : ENV.delete(name)
  end

  test "connection_options maps config to libpq keys and drops pool and adapter" do
    value = {
      host: "db.example", port: 5432, database: "mnemosyne",
      username: "rails_app", password: "secret", pool: 5, adapter: "postgresql"
    }

    assert_equal({ host: "db.example", port: 5432, dbname: "mnemosyne",
                   user: "rails_app", password: "secret" },
      Fd::ChatListener.connection_options(value))
  end

  test "connection_options omits host port user and password when unset" do
    assert_equal({ dbname: "mnemosyne" }, Fd::ChatListener.connection_options(database: "mnemosyne"))
  end

  class FailingConnection
    attr_reader :closed, :listened

    def initialize = (@listened = []; @closed = false)
    def exec(sql) = @listened << sql
    def close = @closed = true
    def wait_for_notify(_wait) = raise(PG::ConnectionBad, "the server went away")
  end

  test "listen closes the connection and raises when wait_for_notify fails" do
    connection = FailingConnection.new

    assert_raises(PG::ConnectionBad) { Fd::ChatListener.new.send(:listen, connection) }

    assert connection.closed, "connection closed after failure"
    assert_equal ["LISTEN fd_chat_changed", "LISTEN fd_conversation_changed", "LISTEN fd_member_guard",
                  "LISTEN fd_member_link", "LISTEN fd_audit_event"], connection.listened
  end

  test "listen does not change the busy connection count of the pool" do
    pool = ActiveRecord::Base.connection_pool

    assert_no_difference -> { pool.stat[:busy] } do
      assert_raises(PG::ConnectionBad) { Fd::ChatListener.new.send(:listen, FailingConnection.new) }
    end
  end
end

require "test_helper"

class Slack::ProxyClientTest < ActiveSupport::TestCase
  setup do
    @url = ENV["INTERNAL_PROXY_URL"]
    @allow = ENV["PROXY_ALLOW_PLAINTEXT"]
    ENV["PROXY_ALLOW_PLAINTEXT"] = nil
  end

  teardown do
    ENV["INTERNAL_PROXY_URL"] = @url
    ENV["PROXY_ALLOW_PLAINTEXT"] = @allow
  end

  test "base_url accepts https for a remote host" do
    ENV["INTERNAL_PROXY_URL"] = "https://proxy.example.com"
    assert_equal "https://proxy.example.com", Slack::ProxyClient.base_url
  end

  test "base_url accepts http for loopback" do
    ENV["INTERNAL_PROXY_URL"] = "http://127.0.0.1:8002"
    assert_equal "http://127.0.0.1:8002", Slack::ProxyClient.base_url
  end

  test "base_url raises NotConfiguredError for http to a remote host" do
    ENV["INTERNAL_PROXY_URL"] = "http://proxy.example.com:8002"
    err = assert_raises(Slack::ProxyClient::NotConfiguredError) { Slack::ProxyClient.base_url }
    assert_match "clear text", err.message
  end

  test "base_url accepts http to a remote host when PROXY_ALLOW_PLAINTEXT is true" do
    ENV["INTERNAL_PROXY_URL"] = "http://proxy.example.com:8002"
    ENV["PROXY_ALLOW_PLAINTEXT"] = "true"
    assert_equal "http://proxy.example.com:8002", Slack::ProxyClient.base_url
  end
end

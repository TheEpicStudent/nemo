require "test_helper"

class CspTest < ActionDispatch::IntegrationTest
  def img_src
    get root_path
    response.headers["Content-Security-Policy"].to_s[/img-src ([^;]*)/, 1].to_s.split
  end

  test "img-src includes slack-edge.com wildcard" do
    assert_includes img_src, "https://*.slack-edge.com"
  end

  test "img-src includes cachet.hackclub.com" do
    assert_includes img_src, "https://cachet.hackclub.com"
  end
end

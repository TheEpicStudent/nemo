require "test_helper"

class FdFilesTest < ActionDispatch::IntegrationTest
  PNG = "\x89PNG\r\n\x1a\n#{"\x00" * 24}".b

  setup do
    sign_in_as(grant_role!("UME", "firefighter"))
  end

  def stored_file(mimetype, body)
    sha = Digest::SHA256.hexdigest(body)
    connection = ApplicationRecord.connection
    connection.exec_query(
      "INSERT INTO fd.intake_file_blobs (sha256, body, size_bytes, mimetype) VALUES ($1, $2, $3, $4) " \
      "ON CONFLICT DO NOTHING",
      "blob", [sha, connection.escape_bytea(body), body.bytesize, mimetype]
    )
    Fd::IntakeFile.create!(slack_file_id: "F#{SecureRandom.hex(4).upcase}", name: "file-1.png",
      mimetype: mimetype, fetch_state: "stored", stored_key: sha, sha256: sha)
  end

  test "file response is sandboxed and not sniffed" do
    file = stored_file("image/png", PNG)

    get fd_file_path(file)

    assert_response :success
    assert_equal Fd::FilesController::SANDBOX, response.headers["Content-Security-Policy"]
    assert_equal "nosniff", response.headers["X-Content-Type-Options"]
    assert_equal "image/png", response.media_type
  end

  test "file that is not an inline image downloads as octet stream" do
    file = stored_file("video/mp4", "\x00\x00\x00\x20ftypisom#{"\x00" * 8}".b)

    get fd_file_path(file)

    assert_equal "application/octet-stream", response.media_type
    assert_match(/\Aattachment/, response.headers["Content-Disposition"])
  end
end

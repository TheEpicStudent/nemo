module Fd
  class FilesController < BaseController
    permit "case.read"

    FALLBACK = "application/octet-stream".freeze
    SANDBOX = "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; sandbox".freeze

    def show
      file = IntakeFile.find(params[:id])
      return head :not_found unless file.stored?

      body = IntakeFileBlob.bytes_for(file.stored_key)
      return head :not_found if body.nil?

      response.headers["Cache-Control"] = "private, max-age=300"
      response.headers["Content-Security-Policy"] = SANDBOX
      response.headers["X-Content-Type-Options"] = "nosniff"
      send_data body,
        type: file.inline? ? file.mimetype : FALLBACK,
        filename: file.display_name,
        disposition: file.inline? ? "inline" : "attachment"
    end
  end
end

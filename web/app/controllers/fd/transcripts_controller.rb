module Fd
  class TranscriptsController < BaseController
    def show
      transcript = ThreadTranscript.for_key(params[:key])
      return head :not_found if transcript.nil?

      audit(transcript, "read", after: { "channel_id" => transcript.channel_id,
                                         "thread_ts" => transcript.thread_ts })

      response.headers["Cache-Control"] = "private, no-store"
      response.headers["X-Content-Type-Options"] = "nosniff"
      response.headers["Referrer-Policy"] = "no-referrer"
      send_data transcript.body, type: "text/plain; charset=utf-8", disposition: "inline"
    end
  end
end

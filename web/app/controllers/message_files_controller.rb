class MessageFilesController < ApplicationController
  before_action { needs(:analytics) }
  before_action :require_reading

  CACHE = "private, max-age=300".freeze
  LOCKED_DOWN = "default-src 'none'; sandbox".freeze

  def show
    channel_id = params[:channel_id]
    ts = params[:ts]
    return head :not_found unless Channels::Activity.visible?(channel_id)

    post = Analytics::FctMessage.post(channel_id, ts)
    return head :not_found if post.nil?
    return head :forbidden unless may_community?("analytics.message.read", post)

    slack_message = Slack::Message.at(channel_id, ts)
    file = Messages::File.in(slack_message.message, params[:file_id])
    return head :not_found if file.nil? || file["url_private"].blank?

    send_file_download(file)
  end

  private

  def send_file_download(file)
    download = Messages::File.bytes_of(file)
    return head :bad_gateway if download.error

    response.headers["Cache-Control"] = CACHE
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = LOCKED_DOWN
    send_data download.bytes, type: download.kind, filename: download.name.presence || params[:file_id],
      disposition: Messages::File.image?(file) ? "inline" : "attachment"
  end
end

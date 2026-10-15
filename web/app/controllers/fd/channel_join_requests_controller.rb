module Fd
  class ChannelJoinRequestsController < BaseController
    permit "channel.guard"

    CHANNEL_ID = /\AC[A-Z0-9]{2,}\z/

    def create
      return redirect_with_alert("Nemo can only join a public channel by itself") unless
        channel_id.match?(CHANNEL_ID)

      join_request = nil
      writing do
        join_request = ChannelJoinRequest.queue!(channel_id: channel_id,
          requested_by: current_account.user_id)
        audit(join_request, "queued", after: { "channel_id" => channel_id })
      end

      join_request = ChannelJoinRequest.wait_for(join_request)
      if join_request.joined?
        redirect_to return_path, notice: "Nemo joined the channel"
      elsif join_request.queued?
        redirect_to return_path, notice: "Nemo has not joined yet, reload in a moment"
      else
        redirect_with_alert(refusal_text(join_request.error))
      end
    end

    private

    def channel_id
      @channel_id ||= params[:channel_id].to_s.strip.upcase
    end

    def return_path
      fd_channel_path(channel_id, tab: params[:tab].presence_in(ChannelsController::TABS))
    end

    def refusal_text(error)
      return FdChannelsHelper::INVITE_NOTE if error == FdChannelsHelper::NEEDS_INVITE

      "Join failed: #{error.presence || 'refused'}"
    end

    def redirect_with_alert(message)
      redirect_to return_path, alert: message
    end
  end
end

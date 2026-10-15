module Fd
  class ThreadSlowmodesController < BaseController
    permit "channel.guard"

    def destroy
      guard = ChannelGuard.thread_slowmodes(channel_id).find_by(id: params[:id])
      return redirect_to(return_path, alert: "Thread slow mode not found") if guard.nil?

      writing do
        guard.update!(state: "lifted", lifted_at: Time.current, lifted_by: current_account.user_id)
        audit(guard, "lifted", after: { "state" => "lifted", "thread_ts" => guard.thread_ts })
      end

      redirect_to return_path, notice: "Thread slow mode disabled"
    end

    private

    def channel_id = params[:channel_id].to_s.strip.upcase

    def return_path = fd_channel_path(channel_id, tab: "slowmode")
  end
end

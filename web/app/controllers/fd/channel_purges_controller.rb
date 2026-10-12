module Fd
  class ChannelPurgesController < BaseController
    permit "channel.purge", only: :create
    permit "channel.guard", only: :show

    MAX_REASON_LENGTH = 500

    def show
      @purge = ChannelPurge.for_channel(channel_id).find(params[:id])
      @channel = Analytics::DimChannel.find_by(channel_id: channel_id)
      @threads = ChannelPurge::Reading.new(@purge.transcript_entries)
      @names = Names.for(@purge.people_named)
    end

    def create
      error = validation_error
      return redirect_with_alert(error) if error

      writing do
        purge = ChannelPurge.create!(channel_id: channel_id, wanted: message_count,
          reason: reason, asked_by: current_account.user_id)
        audit(purge, "queued", after: { "channel_id" => channel_id, "wanted" => message_count })
      end

      redirect_to return_path, notice: "Deleting the last #{message_count} messages in this channel"
    rescue ActiveRecord::RecordNotUnique
      redirect_with_alert("A purge is already running in this channel")
    end

    private

    def channel_id
      @channel_id ||= params[:channel_id].to_s.strip.upcase
    end

    def message_count
      @message_count ||= params[:wanted].to_s.strip.to_i
    end

    def reason
      @reason ||= params[:reason].to_s.strip
    end

    def return_path
      fd_channel_path(channel_id, tab: "purge")
    end

    def validation_error
      unless message_count.between?(1, ChannelPurge::MOST)
        return "say how many, from 1 to #{ChannelPurge::MOST}"
      end
      return "say why" if reason.blank?
      return "keep it under #{MAX_REASON_LENGTH} characters" if reason.length > MAX_REASON_LENGTH
      return "A purge is already running in this channel" if ChannelPurge.waiting_on?(channel_id)

      nil
    end

    def redirect_with_alert(message)
      redirect_to return_path, alert: message
    end
  end
end

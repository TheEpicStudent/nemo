module Fd
  class MemberPurgesController < BaseController
    permit "member.purge", only: :show

    def show
      @purge = ChannelPurge.where(member_id: params[:member_id].to_s.upcase).find(params[:id])
      @channel = @purge.channel_id && Analytics::DimChannel.find_by(channel_id: @purge.channel_id)
      @threads = ChannelPurge::Reading.new(@purge.transcript_entries)
      @failed = @purge.failed_messages
      @names = Names.for(@purge.referenced_user_ids)
      @channels = ChannelNames.for(@purge.items.map(&:channel_id))
      render "fd/channel_purges/show"
    end
  end
end

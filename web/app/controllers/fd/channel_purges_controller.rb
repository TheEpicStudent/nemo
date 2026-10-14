module Fd
  class ChannelPurgesController < BaseController
    permit "channel.purge", only: :create, unless: :one_member?
    permit "member.purge", only: :create, if: :one_member?
    permit "channel.guard", only: :show

    MAX_REASON_LENGTH = 500
    MEMBER_ID = /\A[UW][A-Z0-9]{2,}\z/
    LAST = "last".freeze
    MEMBER = "member".freeze

    def show
      @purge = ChannelPurge.for_channel(channel_id).find(params[:id])
      @channel = Analytics::DimChannel.find_by(channel_id: channel_id)
      @threads = ChannelPurge::Reading.new(@purge.transcript_entries)
      @failed = @purge.failed_messages
      @names = Names.for(@purge.people_named)
    end

    def create
      error = validation_error
      return redirect_with_alert(error) if error

      writing do
        purge = ChannelPurge.create!(channel_id: channel_id, member_id: member_id,
          wanted: message_count, reason: reason, asked_by: current_account.user_id)
        audit(purge, "queued", subject_user_id: member_id,
          after: { "channel_id" => channel_id, "member_id" => member_id, "wanted" => message_count })
      end

      redirect_to return_path, notice: queued_notice
    rescue ActiveRecord::RecordNotUnique
      redirect_with_alert(running_alert)
    end

    private

    def channel_id
      @channel_id ||= params[:channel_id].to_s.strip.upcase
    end

    def one_member? = params[:kind] == MEMBER

    def member_id
      return nil unless one_member?

      @member_id ||= params[:member_id].to_s.strip.delete_prefix("@").upcase.presence
    end

    def message_count
      return params[:member_wanted].to_s.strip.presence&.to_i if one_member?

      @message_count ||= params[:wanted].to_s.strip.to_i
    end

    def count_words
      "the last #{helpers.number_with_delimiter(message_count)} messages"
    end

    def reason
      @reason ||= params[:reason].to_s.strip
    end

    def return_path
      fd_channel_path(channel_id, tab: "purge")
    end

    def member_name = Names.for([member_id])[member_id]

    def queued_notice
      return "Purging #{count_words} in this channel" unless one_member?
      return "Purging every message from #{member_name} in this channel" if message_count.nil?

      "Purging #{count_words} from #{member_name} in this channel"
    end

    def running_alert
      return "A purge of #{member_name} is already running in this channel" if one_member?

      "A purge is already running in this channel"
    end

    def validation_error
      return "pick the member" if one_member? && !member_id.to_s.match?(MEMBER_ID)
      unless (one_member? && message_count.nil?) || message_count.between?(1, ChannelPurge::MOST)
        return "say how many, from 1 to #{helpers.number_with_delimiter(ChannelPurge::MOST)}" \
               "#{', or leave it empty for all of theirs' if one_member?}"
      end
      return "say why" if reason.blank?
      return "keep it under #{MAX_REASON_LENGTH} characters" if reason.length > MAX_REASON_LENGTH
      return running_alert if ChannelPurge.waiting_on?(channel_id, member_id)

      nil
    end

    def redirect_with_alert(message)
      redirect_to return_path, alert: message
    end
  end
end

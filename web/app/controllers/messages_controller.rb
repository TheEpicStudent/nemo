class MessagesController < ApplicationController
  before_action { needs(:analytics) }
  before_action :require_reading

  def show
    @channel_id = params[:channel_id]
    @ts = params[:ts]
    @channel = Analytics::DimChannel.find_by(channel_id: @channel_id)
    @activity_visible = Channels::Activity.visible?(@channel_id)
    @post = Analytics::FctMessage.post(@channel_id, @ts) if @activity_visible
    return unless @post

    unless may_community?("analytics.message.read", @post)
      return redirect_forbidden("analytics.message.read", @post)
    end

    @slack_message = Slack::Message.at(@channel_id, @ts)
    @names = Fd::Names.for([@post.author_id] + Fd::Mentions.ids(@slack_message.message&.dig("text")))
    @mentioned_channels = Analytics::DimChannel
      .where(channel_id: Fd::Mentions.channel_ids(@slack_message.message&.dig("text")))
      .pluck(:channel_id, :name).to_h
    @emoji = Slack::Emoji.for(Slack::RichText.emoji_names(@slack_message.message))
    @member_count = Analytics::FctChannelSpan.where(channel_id: @channel_id).pick(:total_members)
    @span = Messages::Activity::SPANS.key?(params[:span]) ? params[:span] :
      Messages::Activity.span_for(@post.posted_at)
    @activity = @post.is_reply ? nil : Messages::Activity.for(@channel_id, @ts, posted_at: @post.posted_at)
  end
end

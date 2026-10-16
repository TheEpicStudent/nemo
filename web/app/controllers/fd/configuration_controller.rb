module Fd
  class ConfigurationController < BaseController
    permit "app.configure"

    TABS = %w[automod domains responses categories tags].freeze
    LIST_LIMIT = 50
    TAG_LIMIT = 100

    def show
      @tab = params[:tab].presence_in(TABS) || TABS.first
      @words = AutomodWord.watching
      @retired = AutomodWord.retired.newest_first.limit(LIST_LIMIT).to_a
      @matches = AutomodMatch.newest_first.limit(LIST_LIMIT).to_a
      load_domains
      load_responses
      load_tags if @tab == "tags"
      load_categories if @tab == "categories"
      @channels = ChannelNames.for(@matches.map(&:channel_id) + [@autoresponse_channel])
      @names = Names.for([@words.flat_map(&:people_named),
                          @retired.flat_map(&:people_named),
                          @matches.map(&:user_id),
                          @domains.flat_map(&:people_named),
                          @retired_domains.flat_map(&:people_named),
                          @screens.map(&:user_id),
                          Array(@tags).map(&:created_by)])
    end

    private

    def load_domains
      @domains = BlockedDomain.watching
      @retired_domains = BlockedDomain.retired.newest_first.limit(LIST_LIMIT).to_a
      @screens = JoinScreen.caught.recent_first.limit(LIST_LIMIT).to_a
    end

    def load_tags
      @tag_total = Tag.count
      @tags = Tag.with_uses
        .order(Arel.sql("MAX(fd.case_tags.added_at) DESC NULLS LAST, fd.tags.name"))
        .limit(TAG_LIMIT).to_a
    end

    def load_categories
      active, retired = InfractionCategory.ordered.to_a.partition { |category| !category.retired? }
      @categories = active + retired
      @active_count = active.size
      @category_cases = Case.where.not(category_key: nil).group(:category_key).count
    end

    def load_responses
      @autoresponse_on = AppSetting.on?(AppSetting::AUTORESPONSE_ON)
      @autoresponse_emoji = AppSetting.autoresponse_emoji
      @autoresponse_channel = AppSetting.value(AppSetting::AUTORESPONSE_CHANNEL)
      @autoresponse_seat = ChannelMembership.seat(@autoresponse_channel) if @autoresponse_channel.present?
      @autoresponse_body = AppSetting.value(AppSetting::AUTORESPONSE_BODY)
      @autoresponse_cooldown = AppSetting.autoresponse_cooldown_days
      @unsub_on = AppSetting.on?(AppSetting::UNSUB_SHIELD_ON)
      @unsub_link = AppSetting.value(AppSetting::UNSUB_SHIELD_LINK)
    end
  end
end

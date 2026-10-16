module Admin
  class ChannelsController < BaseController
    SEARCH_LIMIT = 100

    BANDS = [
      ["public", "All signed-in users"],
      ["granted", "Granted users"]
    ].freeze

    PICKER_LIMIT = 40

    def search
      term = params[:q].to_s.strip.delete_prefix("#")
      scope = Analytics::DimChannel.where(archived: false)
      if term.present?
        like = "%#{ActiveRecord::Base.sanitize_sql_like(term)}%"
        scope = scope.where("dim_channel.name ILIKE :like OR " \
                            "dim_channel.channel_id ILIKE :like", like: like)
      end

      render json: {
        channels: order_by_member_count(scope).limit(PICKER_LIMIT)
          .pluck(:channel_id, :name).map { |id, name| { id: id, name: name } },
        total: scope.count
      }
    end

    CHANNEL_SPAN_JOIN = "LEFT JOIN analytics.fct_channel_span s " \
                        "ON s.channel_id = dim_channel.channel_id".freeze

    def order_by_member_count(scope)
      scope.joins(CHANNEL_SPAN_JOIN).order(Arel.sql("s.total_members DESC NULLS LAST, dim_channel.name"))
    end

    def index
      @q = params[:q].to_s.strip
      @settings = Channels::Audience::Setting.all.index_by(&:channel_id)
      @grants = Channels::Audience::Grant.live.to_a.group_by(&:channel_id)
      @activity = Channels::Activity.visible_ids.to_set
      @total = Analytics::DimChannel.where(archived: false).count
      @bands = group_by_audience(listed_channels)
      @open = @bands.reject { |kind, _label, _rows| kind == "granted" }
        .sum { |_kind, _label, rows| rows.size }
      grant_rows = @grants.values.flatten
      @names = Fd::Names.for(grant_rows.map(&:user_id) + grant_rows.map(&:granted_by))
    end

    def update
      return redirect_forbidden unless may_community?("analytics.channel.share")

      requested_audience = params[:audience].to_s
      unless Channels::Audience::KINDS.include?(requested_audience)
        return redirect_to(admin_channels_path, alert: "#{requested_audience} is not an audience")
      end

      row = Channels::Audience::Setting.find_or_initialize_by(channel_id: params[:channel_id])
      previous_audience = row.audience
      row.update!(audience: requested_audience, set_by: current_account.user_id, set_at: Time.current)
      Fd::Audit.record(row, requested_audience == "granted" ? "revoked" : "granted",
        actor: current_account.user_id, request_id: request.request_id,
        entity_id: row.channel_id,
        before: { "channel_id" => row.channel_id, "audience" => previous_audience },
        after: { "channel_id" => row.channel_id, "audience" => requested_audience })
      redirect_to admin_channels_path(q: params[:q].presence),
        notice: "##{params[:channel_id]} is #{requested_audience}"
    end

    ACTIVITY_STATES = %w[on off].freeze

    def activity
      return redirect_forbidden("analytics.message.show") unless may_community?("analytics.message.show")

      requested_state = params[:shown].to_s
      unless ACTIVITY_STATES.include?(requested_state)
        return redirect_to(admin_channels_path, alert: "#{requested_state} is not on or off")
      end

      channel_id = params[:channel_id]
      row = Channels::Activity::Setting.find_or_initialize_by(channel_id: channel_id)
      previously_on = row.persisted?
      if requested_state == "on"
        row.update!(set_by: current_account.user_id, set_at: Time.current)
      elsif previously_on
        row.destroy!
      end
      Fd::Audit.record(row, requested_state == "on" ? "turned_on" : "turned_off",
        actor: current_account.user_id, request_id: request.request_id,
        entity_id: channel_id,
        before: { "channel_id" => channel_id, "shown" => previously_on },
        after: { "channel_id" => channel_id, "shown" => requested_state == "on" })
      redirect_to admin_channels_path(q: params[:q].presence),
        notice: "Message activity #{requested_state} for ##{channel_id}"
    end

    private

    def like_q
      ActiveRecord::Base.sanitize_sql_like(@q)
    end

    def redirect_forbidden(key = "analytics.channel.share")
      redirect_to admin_channels_path, alert: Community::Access.why_not(current_account, key)
    end

    def listed_channels
      scope = Analytics::DimChannel.where(archived: false)
      if @q.present?
        return scope.where("dim_channel.name ILIKE ?", "%#{like_q}%")
          .order(:name).limit(SEARCH_LIMIT)
      end


      open_ids = @settings.values.select { |row| Channels::Audience::OPEN.include?(row.audience) }
        .map(&:channel_id)
      scope.where(channel_id: open_ids).or(scope.where(channel_id: @grants.keys))
        .or(scope.where(channel_id: @activity.to_a)).order(:name)
    end

    def group_by_audience(channels)
      grouped = channels.group_by { |channel| audience(channel.channel_id) }
      BANDS.filter_map { |kind, label|
        rows = grouped[kind]
        [kind, label, rows] if rows.present?
      }
    end

    def audience(channel_id)
      Channels::Audience.normalize(@settings[channel_id]&.audience ||
        Channels::Audience::DEFAULT)
    end
    helper_method :audience
  end
end

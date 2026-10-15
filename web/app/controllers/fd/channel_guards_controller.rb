module Fd
  class ChannelGuardsController < BaseController
    permit "channel.guard"

    def create
      return redirect_with_alert("That is not a valid guard kind") unless ChannelGuard.kind?(kind)
      return redirect_with_alert("This channel is already guarded") if live_guard

      error = settings_error
      return redirect_with_alert(error) if error

      restored_count = 0
      writing do
        guard = ChannelGuard.create!(kind: kind, channel_id: channel_id,
          settings: requested_settings, opened_by: current_account.user_id, **slowmode_attributes,
          **(slowmode? ? { notice_wanted: true } : {}))
        audit(guard, "opened", after: guard.settings.merge(slowmode_audit(guard)))
        restored_count = restore_allows(guard) unless slowmode?
      end

      return redirect_to(return_path, notice: "Slow mode enabled · #{ends_label}") if slowmode?

      redirect_to return_path, notice: turned_on_notice(restored_count)
    end

    def update
      guard = live_guard
      return redirect_with_alert("This channel is not guarded that way") if guard.nil?
      return extend_slowmode(guard) if slowmode?

      error = settings_error
      return redirect_with_alert(error) if error

      previous_settings = guard.settings
      writing do
        guard.update!(settings: previous_settings.merge(requested_settings), updated_at: Time.current)
        audit(guard, "tuned", before: previous_settings, after: guard.settings)
      end

      redirect_to return_path, notice: "#{guard_label_text.upcase_first} updated"
    end

    def destroy
      guard = live_guard
      return redirect_with_alert("This channel is not guarded that way") if guard.nil?

      writing do
        guard.update!(state: "lifted", lifted_at: Time.current,
          lifted_by: current_account.user_id)
        audit(guard, "lifted")
      end

      return redirect_to(return_path, notice: "Slow mode disabled") if slowmode?

      redirect_to return_path, notice: "#{guard_label_text.upcase_first} turned off; the list is kept"
    end

    private

    def extend_slowmode(guard)
      ends, error = slowmode_end(params[:extend_by], from: guard.expires_at)
      return redirect_with_alert(error || "Select how long to extend") if ends.nil?

      previous_end = guard.expires_at
      writing do
        guard.update!(expires_at: ends, updated_at: Time.current)
        audit(guard, "extended", before: { "expires_at" => previous_end&.iso8601 },
          after: { "expires_at" => ends.iso8601 })
      end

      redirect_to return_path, notice: "Slow mode extended · ends #{ShortDate.ending(ends)}"
    end

    def slowmode_end(key, from: nil)
      key = key.to_s
      if ChannelGuard::DURATIONS.key?(key)
        return [[from, Time.current].compact.max + ChannelGuard::DURATIONS.fetch(key), nil]
      end
      return [nil, nil] unless key == ChannelGuard::CUSTOM

      ends, error = EndTime.read(params[:expires_on], params[:expires_time])
      return [nil, error] if error
      return [nil, "Enter the end date"] if ends.nil?
      return [nil, "End must be in the future"] if ends <= Time.current

      [ends, nil]
    end

    def starting_end = @starting_end ||= slowmode_end(params[:duration])

    def ends_label
      ends = starting_end.first
      ends ? "ends #{ShortDate.ending(ends)}" : "no end date"
    end

    def channel_id
      @channel_id ||= params[:channel_id].to_s.strip.upcase
    end

    def kind
      @kind ||= params[:kind].to_s
    end

    def live_guard
      @live_guard ||= ChannelGuard.live_for(channel_id, kind: kind)
    end

    def last_lifted_guard
      ChannelGuard.of_kind(kind).channel_wide.where(channel_id: channel_id, state: "lifted")
        .order(lifted_at: :desc, id: :desc).first
    end

    def restore_allows(guard)
      previous_guard = last_lifted_guard
      return 0 if previous_guard.nil?

      previous_guard.allows.oldest_first.each do |previous_allow|
        allow = guard.allows.create!(subject_id: previous_allow.subject_id,
          label: previous_allow.label, added_by: previous_allow.added_by,
          added_at: previous_allow.added_at)
        audit(allow, "added", entity_id: guard.id,
          after: { "subject_id" => allow.subject_id, "label" => allow.label,
                   "restored_from_guard_id" => previous_guard.id })
      end
      previous_guard.allows.size
    end

    def turned_on_notice(restored_count)
      notice = "#{guard_label_text.upcase_first} turned on"
      restored_count.positive? ? "#{notice}, #{restored_count} kept on the list" : notice
    end

    def guard_label_text
      FdChannelsHelper::GUARD_LABELS.fetch(kind, kind).downcase
    end

    def return_path
      fd_channel_path(channel_id, tab: kind)
    end

    def requested_settings
      case kind
      when ChannelGuard::SLOWMODE
        { "seconds" => seconds, "threads" => params[:threads].present? }
      when ChannelGuard::READONLY
        { "threads" => params[:threads].present? }
      when ChannelGuard::ACCOUNT_AGE
        { "min_age_days" => min_age_days }
      else
        {}
      end
    end

    def slowmode? = kind == ChannelGuard::SLOWMODE

    def slowmode_attributes
      return {} unless slowmode?

      { reason: params[:reason].to_s.strip, expires_at: starting_end.first }
    end

    def slowmode_audit(guard)
      return {} unless slowmode?

      { "reason" => guard.reason, "expires_at" => guard.expires_at&.iso8601 }
    end

    def seconds
      value = params[:seconds].to_s.strip
      value.present? ? value.to_i : ChannelGuard::SECONDS_TO_START
    end

    def min_age_days
      value = params[:min_age_days].to_s.strip
      value.present? ? value.to_i : ChannelGuard::DAYS_TO_START
    end

    def settings_error
      case kind
      when ChannelGuard::SLOWMODE
        if params[:seconds].to_s.strip.present? && !seconds.between?(1, ChannelGuard::SLOWEST)
          return "Enter 1 to #{ChannelGuard::SLOWEST} seconds"
        end
        error = starting_end.last
        return error if error
        return "Enter a reason" if params[:reason].to_s.strip.blank?
      when ChannelGuard::ACCOUNT_AGE
        return nil if params[:min_age_days].to_s.strip.blank?
        return "say how many days, from 1 to #{ChannelGuard::OLDEST}" unless
          min_age_days.between?(1, ChannelGuard::OLDEST)
      end

      nil
    end

    def redirect_with_alert(message)
      redirect_to fd_channel_path(channel_id, tab: ChannelGuard.kind?(kind) ? kind : nil),
        alert: message
    end
  end
end

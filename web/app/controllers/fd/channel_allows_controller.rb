module Fd
  class ChannelAllowsController < BaseController
    permit "channel.guard"

    MEMBER_ID = /\A[UWB][A-Z0-9]{2,}\z/

    def create
      guard = live_guard
      return redirect_with_alert("This channel is not guarded") if guard.nil?

      subject_ids = requested_subject_ids
      return redirect_with_alert("Select who to allow") if subject_ids.empty?
      unless subject_ids.all? { |id| id.match?(MEMBER_ID) }
        return redirect_with_alert("That is not a valid member id")
      end

      added = []
      writing do
        subject_ids.each do |subject_id|
          next if guard.allows.exists?(subject_id: subject_id)

          allow = guard.allows.create!(subject_id: subject_id, label: label_for(subject_id),
            added_by: current_account.user_id)
          audit(allow, "added", entity_id: guard.id)
          added << subject_id
        end
      end

      redirect_to fd_channel_path(channel_id, tab: kind), notice: allowed_notice(added, subject_ids)
    end

    def destroy
      guard = live_guard
      return redirect_with_alert("This channel is not guarded") if guard.nil?

      allow = guard.allows.find_by(subject_id: params[:id].to_s.strip.upcase)
      return redirect_with_alert("That bot is not on the list") if allow.nil?

      writing do
        audit(allow, "removed", entity_id: guard.id,
          before: { "subject_id" => allow.subject_id, "label" => allow.label }, after: nil)
        allow.destroy!
      end

      redirect_to fd_channel_path(channel_id, tab: kind),
        notice: "#{allow.name} removed from the list"
    end

    private

    def channel_id
      @channel_id ||= params[:channel_id].to_s.strip.upcase
    end

    def kind
      @kind ||= params[:kind].to_s
    end

    def live_guard
      @live_guard ||= ChannelGuard.live_for(channel_id, kind: kind)
    end

    def requested_subject_ids
      raw = params[:subject_ids].presence || [params[:subject_id]]
      Array(raw).map { |id| id.to_s.strip.delete_prefix("@").upcase }.reject(&:blank?).uniq
    end

    def label_for(subject_id)
      Member.find_by(user_id: subject_id)&.name
    end

    def allowed_notice(added, subject_ids)
      return "everything you picked was already allowed here" if added.empty?

      names = added.map { |id| label_for(id) || id }.to_sentence
      note = "#{names} may post here"
      added.size < subject_ids.size ? "#{note}, the rest were already on the list" : note
    end

    def redirect_with_alert(message)
      redirect_to fd_channel_path(channel_id, tab: kind), alert: message
    end
  end
end

module Api
  module V1
    class ChannelManagersController < BaseController
      CHANNEL = /\AC[A-Z0-9]{8,}\z/
      MEMBER = /\A[UW][A-Z0-9]{8,}\z/
      CAPABILITY = "channel_manager".freeze

      def show
        channel = params[:channel_id].to_s
        user = params[:user_id].to_s

        return render_error(:unprocessable_content, "bad_channel_id") unless CHANNEL.match?(channel)
        return render_error(:unprocessable_content, "bad_user_id") unless MEMBER.match?(user)

        render json: { channel_id: channel, user_id: user }.merge(answer(channel, user))
      end

      private

      def answer(channel, user)
        unless ::Api::Consent.granted?(user, current_token.app_id, CAPABILITY)
          return no_consent_response(channel, user)
        end

        ChannelManagers.refresh_if_stale(channel)
        assignment = ::Api::ChannelManager.find_by(channel_id: channel, user_id: user)
        log(channel, user, assignment ? ::Api::RequestLog::MANAGER : ::Api::RequestLog::NOT_MANAGER)

        { consent: "granted", is_manager: assignment.present? }.merge(sync_status(channel))
      end

      def no_consent_response(channel, user)
        log(channel, user, ::Api::RequestLog::WITHHELD)

        { consent: "withheld", is_manager: nil, opt_in_url: "#{request.base_url}/settings/permissions" }
      end

      def sync_status(channel)
        synced_at = ChannelManagers.swept_at(channel)

        { synced_at: synced_at&.utc&.iso8601,
          stale: synced_at.nil? || synced_at < ChannelManagers::TTL.ago }
      end

      def log(channel, user, outcome)
        ::Api::RequestLog.log!(current_token.id, channel, [[user, outcome]])
      end
    end
  end
end

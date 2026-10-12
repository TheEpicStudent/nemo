module Api
  module V1
    class BaseController < ActionController::API
      BEARER = /\ABearer (.+)\z/i

      WINDOW = 60
      BUCKET_TTL = 2.minutes

      before_action :require_token
      before_action :approved_for_scope
      before_action :within_budget

      private

      def approved_for_scope
        return if ::Api::Approval.active?(current_token.app_id)

        render_error(:forbidden, "not_approved")
      end

      attr_reader :current_token

      def within_budget
        limit = current_token.rate
        used = Rails.cache.increment(bucket, 1, expires_in: BUCKET_TTL).to_i
        budget!(limit, used)
        return if used <= limit

        response.headers["Retry-After"] = seconds_until_reset.to_s
        render_error(:too_many_requests, "rate_limited", retry_after: seconds_until_reset)
      end

      def bucket
        "api/rate/#{current_token.id}/#{Time.current.to_i / WINDOW}"
      end

      def seconds_until_reset
        WINDOW - (Time.current.to_i % WINDOW)
      end

      def budget!(limit, used)
        response.headers["RateLimit-Limit"] = limit.to_s
        response.headers["RateLimit-Remaining"] = [limit - used, 0].max.to_s
        response.headers["RateLimit-Reset"] = seconds_until_reset.to_s
      end

      def require_token
        return render_error(:service_unavailable, "api_off") if Fd::Flag.off?(:public_api)

        key = bearer_token
        return render_error(:unauthorized, "invalid_token") if key.blank?

        token = ::Api::Token.find_by(digest: ::Api::Token.digest_of(key))
        return render_error(:unauthorized, "invalid_token") if token.nil?
        return render_error(:unauthorized, "revoked_token") if token.revoked?
        return render_error(:unauthorized, "expired_token") if token.expired?

        @current_token = token
        token.used!
      end

      def bearer_token
        request.authorization.to_s[BEARER, 1]
      end

      CALLER_ERROR_MESSAGES = {
        "api_off" => "the public_api flag is off",
        "invalid_token" => "no live key matches that digest",
        "revoked_token" => "that key was revoked, do not retry",
        "expired_token" => "that key reached its expiry date, mint a new one",
        "bad_channel_id" => "channel_id must match /\\AC[A-Z0-9]{8,}\\z/",
        "bad_user_id" => "every user id must match /\\A[UW][A-Z0-9]{8,}\\z/",
        "rate_limited" => "rate limit spent, see retry_after",
        "not_approved" => "this app is not approved, ask for access"
      }.freeze

      CALLER_ERRORS = [
        [401, "invalid_token", "Absent, malformed, or unknown Authorization header."],
        [401, "revoked_token", "Key exists but was revoked. Not retryable."],
        [401, "expired_token", "Key passed its expiry date. Mint a new one."],
        [422, "bad_channel_id", "channel_id did not match the pattern above."],
        [422, "bad_user_id", "user_id did not match the pattern above."],
        [403, "not_approved", "The app behind this key is not approved."],
        [429, "rate_limited", "Budget spent. Retry after retry_after seconds."],
        [503, "api_off", "The public_api flag is off. Applies to every route."]
      ].freeze

      def render_error(status, error, **extra)
        render json: { error: error, message: CALLER_ERROR_MESSAGES[error] }.compact.merge(extra), status: status
      end
    end
  end
end

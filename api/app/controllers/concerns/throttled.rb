# frozen_string_literal: true

# Throttled adds a simple in-memory, per-client rate limit to a controller.
# Honors the Appendix A 429 contract: { error: "Rate limit exceeded", retry_after: 60 }
# plus a Retry-After header. In-process only (single Puma worker), which is sufficient for
# the Gauntlet demo; use Rack::Attack + Redis for a multi-process production deployment.
module Throttled
  extend ActiveSupport::Concern

  WINDOW = Integer(ENV.fetch("RATE_LIMIT_WINDOW_SECONDS", "60"))
  HITS = Hash.new { |store, key| store[key] = [] }
  LOCK = Mutex.new

  included do
    before_action :enforce_rate_limit
  end

  # Clears all recorded hits. Test-only helper.
  def self.reset!
    LOCK.synchronize { HITS.clear }
  end

  private

  # Rejects with 429 once the client exceeds RATE_LIMIT_MAX hits in the current window.
  def enforce_rate_limit
    max = Integer(ENV.fetch("RATE_LIMIT_MAX", "60"))
    return if max <= 0
    return if record_hit(rate_limit_key) <= max

    response.headers["Retry-After"] = WINDOW.to_s
    render json: { error: "Rate limit exceeded", retry_after: WINDOW },
           status: :too_many_requests
  end

  # Records a hit for key within the rolling window and returns the current count.
  def record_hit(key)
    now = Time.now.to_f
    LOCK.synchronize do
      recent = HITS[key].select { |seen| seen > now - WINDOW }
      recent << now
      HITS[key] = recent
      recent.size
    end
  end

  # Per-client key: the bearer token when present, otherwise the remote IP.
  def rate_limit_key
    token = request.headers["Authorization"].to_s.delete_prefix "Bearer "
    token.empty? ? request.remote_ip : token
  end
end

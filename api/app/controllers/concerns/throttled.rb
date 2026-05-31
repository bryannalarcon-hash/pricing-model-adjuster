# frozen_string_literal: true

# Adds per-client in-memory rate limiting (single-process).
# 429 contract: { error: "Rate limit exceeded", retry_after: <window> } + Retry-After header.
# Set RATE_LIMIT_MAX and RATE_LIMIT_WINDOW_SECONDS to configure.
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

  def enforce_rate_limit
    max = Integer(ENV.fetch("RATE_LIMIT_MAX", "60"))
    return if max <= 0
    return if record_hit(rate_limit_key) <= max

    response.headers["Retry-After"] = WINDOW.to_s
    render json: { error: "Rate limit exceeded", retry_after: WINDOW },
           status: :too_many_requests
  end

  def record_hit(key)
    now = Time.now.to_f
    LOCK.synchronize do
      recent = HITS[key].select { |seen| seen > now - WINDOW }
      recent << now
      HITS[key] = recent
      recent.size
    end
  end

  def rate_limit_key
    token = request.headers["Authorization"].to_s.delete_prefix "Bearer "
    token.empty? ? request.remote_ip : token
  end
end

# frozen_string_literal: true

# Authenticated enforces HTTP method and Bearer token auth on a controller.
# Rejects non-POST with 405 and missing/invalid tokens with 401.
module Authenticated
  extend ActiveSupport::Concern

  included do
    before_action :enforce_post_method
    before_action :authenticate!
  end

  private

  def enforce_post_method
    return if request.post?

    render json: { error: "Method not allowed" }, status: :method_not_allowed
  end

  def authenticate!
    secret = ENV.fetch("GAUNTLET_PRICING_SECRET", "")
    authz  = request.headers["Authorization"].to_s

    unless authz.start_with?("Bearer ") &&
           ActiveSupport::SecurityUtils.secure_compare(
             authz.delete_prefix("Bearer "), secret
           )
      render json: { error: "Unauthorized" }, status: :unauthorized
    end
  end
end

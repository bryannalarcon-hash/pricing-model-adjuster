# Handles POST /pricing-estimate and POST /.netlify/functions/pricing-estimate.
#
# Auth: Bearer token via constant-time compare (ActiveSupport::SecurityUtils.secure_compare).
# Proxies validated payload to the Python inference sidecar and returns the Appendix A response shape.
class PricingEstimateController < ApplicationController
  REQUIRED_FIELDS = %w[job_id service_category zip_code job_description].freeze

  before_action :enforce_post_method
  before_action :authenticate!
  before_action :parse_json_body
  before_action :validate_required_fields

  def create
    result = SidecarClient.infer(booking_params)
    render json: {
      ok: true,
      job_id: booking_params["job_id"],
      estimate_lo: result[:estimate_lo],
      estimate_hi: result[:estimate_hi],
      estimate_midpoint: result[:estimate_midpoint],
      confidence: result[:confidence],
      model_version: result.fetch(:model_version, "gauntlet-v1.0.0")
    }, status: :ok
  rescue SidecarClient::UnavailableError
    render json: { error: "inference unavailable" }, status: :internal_server_error
  rescue SidecarClient::InferenceError => e
    render json: { error: e.message }, status: :internal_server_error
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
           ActiveSupport::SecurityUtils.secure_compare(authz.delete_prefix("Bearer "), secret)
      render json: { error: "Unauthorized" }, status: :unauthorized
    end
  end

  def parse_json_body
    body = request.body.read
    @parsed_body = JSON.parse(body)
  rescue JSON::ParserError
    render json: { error: "Malformed JSON" }, status: :bad_request
  end

  def validate_required_fields
    REQUIRED_FIELDS.each do |field|
      value = @parsed_body[field]
      if value.nil? || (value.respond_to?(:strip) && value.strip.empty?)
        render json: { error: "#{field} required" }, status: :bad_request
        return
      end
    end
  end

  def booking_params
    @booking_params ||= @parsed_body.slice(
      "job_id", "service_category", "zip_code", "job_description",
      "service_subtype", "deadline", "booking_month", "job_status",
      "original_estimate", "original_estimate_lo", "original_estimate_hi"
    )
  end
end

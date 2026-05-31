# Handles POST /pricing-estimate and POST /.netlify/functions/pricing-estimate.
# Proxies the validated payload to the Python inference sidecar and returns
# the Appendix A response shape.
class PricingEstimateController < ApplicationController
  include Throttled
  include Authenticated
  include Validated

  # @return [void]
  def create
    result = SidecarClient.infer(booking_params)
    render json: {
      ok: true,
      job_id: booking_params["job_id"],
      estimate_lo: result[:estimate_lo],
      estimate_hi: result[:estimate_hi],
      estimate_midpoint: result[:estimate_midpoint],
      confidence: result[:confidence],
      model_version: result.fetch(:model_version, "gauntlet-v2.1.0")
    }, status: :ok
  rescue SidecarClient::UnavailableError
    render json: { error: "inference unavailable" }, status: :internal_server_error
  rescue SidecarClient::InferenceError => error
    render json: { error: error.message }, status: :internal_server_error
  end
end

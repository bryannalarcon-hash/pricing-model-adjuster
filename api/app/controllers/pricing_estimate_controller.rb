# Handles POST /pricing-estimate and POST /.netlify/functions/pricing-estimate.
# Proxies the validated payload to the Python inference sidecar and returns
# the Appendix A response shape. Fires a non-blocking auto-send when configured.
class PricingEstimateController < ApplicationController
  include Throttled
  include Authenticated
  include Validated

  # @return [void]
  def create
    result = SidecarClient.infer(booking_params)
    auto_send_to_booking(result)
    render json: {
      ok: true,
      job_id: booking_params["job_id"],
      estimate_lo: result[:estimate_lo],
      estimate_hi: result[:estimate_hi],
      estimate_midpoint: result[:estimate_midpoint],
      confidence: result[:confidence],
      model_version: result.fetch(:model_version, "gauntlet-v2.1.0"),
      uncertainties: result[:uncertainties]
    }, status: :ok
  rescue SidecarClient::UnavailableError
    render json: { error: "inference unavailable" }, status: :internal_server_error
  rescue SidecarClient::InferenceError => error
    render json: { error: error.message }, status: :internal_server_error
  end

  private

  # Fires a fire-and-forget booking send when auto-send is enabled for this request's
  # source: website requests (proxied from /dashboard/predict via X-Pricing-Source) use
  # website_auto_send; direct API calls use api_auto_send. Threaded; never blocks the response.
  # @param result [Hash] sidecar inference result (symbol keys)
  # @return [void]
  def auto_send_to_booking(result)
    website = request.headers["X-Pricing-Source"] == "website"
    return unless website ? BookingConfig.website_auto_send? : BookingConfig.api_auto_send?

    src    = website ? "website" : "api"
    params = booking_params.dup
    Thread.new { BookingClient.auto_send(params, result, source: src) rescue nil }
  end
end

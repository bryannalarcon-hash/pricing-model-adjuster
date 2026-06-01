require "csv"

# Serves the SPA shell + the JSON routes the SPA calls. Reads demo metrics and
# predictions from the in-image dashboard_data/ copy (shipped because the rails
# build context is api/), preferring repo-root eval outputs when present (dev).
# Proxy logic lives in PricingProxy to keep this within the 50-line limit.
class DashboardController < ApplicationController
  METRICS_PATHS = [Rails.root.join("..", "reports", "eval_metrics.json"),
                   Rails.root.join("dashboard_data", "eval_metrics.json")].freeze
  PREDICTIONS_PATHS = [Rails.root.join("..", "predictions", "predictions.csv"),
                       Rails.root.join("dashboard_data", "predictions.csv")].freeze
  PREDICTIONS_CAP = 500

  # @return [void]
  def predict
    payload = JSON.parse(request.raw_post)
    result  = PricingProxy.forward(payload, base: request.base_url)
    render json: result[:body], status: result[:status]
  rescue JSON::ParserError
    render json: { error: "Malformed JSON" }, status: :bad_request
  end

  # @return [void]
  def metrics
    render json: JSON.parse(File.read(first_existing(METRICS_PATHS)))
  rescue Errno::ENOENT, TypeError
    render json: { error: "metrics unavailable" }, status: :service_unavailable
  end

  # @return [void]
  def predictions
    rows = CSV.read(first_existing(PREDICTIONS_PATHS), headers: true)
              .first(PREDICTIONS_CAP).map(&:to_h)
    render json: rows
  rescue Errno::ENOENT, TypeError
    render json: { error: "predictions unavailable" }, status: :service_unavailable
  end

  private

  # @return [Pathname, nil] first path that exists on disk
  def first_existing(paths) = paths.find { |p| File.exist?(p) }
end

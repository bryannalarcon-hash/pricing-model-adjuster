require "csv"

# Serves the static SPA shell and the three JSON routes the SPA calls.
# Proxy logic is delegated to PricingProxy to stay within the 50-line limit.
class DashboardController < ApplicationController
  METRICS_PATH = Rails.root.join("..", "reports", "eval_metrics.json")
  PREDICTIONS_PATH = Rails.root.join("..", "predictions", "predictions.csv")
  PREDICTIONS_CAP = 500

  # @return [void]
  def index
    send_file Rails.root.join("public", "dashboard", "index.html"),
              type: "text/html"
  end

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
    raw = File.read(METRICS_PATH)
    render json: JSON.parse(raw)
  rescue Errno::ENOENT
    render json: { error: "metrics unavailable" }, status: :service_unavailable
  end

  # @return [void]
  def predictions
    rows = CSV.read(PREDICTIONS_PATH, headers: true)
              .first(PREDICTIONS_CAP)
              .map(&:to_h)
    render json: rows
  rescue Errno::ENOENT
    render json: { error: "predictions unavailable" }, status: :service_unavailable
  end
end

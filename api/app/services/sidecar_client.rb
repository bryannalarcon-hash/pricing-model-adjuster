require "net/http"
require "json"
require "uri"

# Proxies inference requests to the Python sidecar service.
#
# The sidecar is expected at SIDECAR_URL (default: http://127.0.0.1:8011/infer).
# Uses a 5-second read/open timeout. If the sidecar is unreachable or returns
# a non-200 response, raises the appropriate error.
module SidecarClient
  SIDECAR_URL = ENV.fetch("SIDECAR_URL", "http://127.0.0.1:8011/infer")
  TIMEOUT_SECONDS = 5

  # Raised when the sidecar is unreachable (connection refused, timeout, etc.)
  class UnavailableError < StandardError; end

  # Raised when the sidecar returns a non-200 response or unreadable body.
  class InferenceError < StandardError; end

  # Posts booking_params JSON to the sidecar and returns a symbolized result hash.
  # Keys returned: :estimate_lo, :estimate_hi, :estimate_midpoint, :confidence,
  #                :model_version (and optionally :coverage, :uncertainties)
  def self.infer(booking_params)
    uri  = URI.parse(SIDECAR_URL)
    http = Net::HTTP.new(uri.host, uri.port)
    http.open_timeout = TIMEOUT_SECONDS
    http.read_timeout = TIMEOUT_SECONDS

    request = Net::HTTP::Post.new(uri.request_uri, "Content-Type" => "application/json")
    request.body = booking_params.to_json

    response = http.request(request)

    unless response.is_a?(Net::HTTPSuccess)
      raise InferenceError, "sidecar returned #{response.code}"
    end

    body = JSON.parse(response.body, symbolize_names: true)

    {
      estimate_lo:       body[:estimate_lo],
      estimate_hi:       body[:estimate_hi],
      estimate_midpoint: body[:estimate_midpoint],
      confidence:        body[:confidence],
      model_version:     body.fetch(:model_version, "gauntlet-v1.0.0"),
      coverage:          body[:coverage],
      uncertainties:     body[:uncertainties]
    }
  rescue Errno::ECONNREFUSED, Errno::ECONNRESET, Errno::EHOSTUNREACH,
         Net::OpenTimeout, Net::ReadTimeout, SocketError
    raise UnavailableError, "inference unavailable"
  rescue JSON::ParserError
    raise InferenceError, "sidecar returned invalid JSON"
  end
end

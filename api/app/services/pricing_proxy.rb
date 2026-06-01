require "net/http"
require "json"
require "uri"

# Forwards a booking payload to the app's own /pricing-estimate with an
# injected bearer token, keeping the secret out of browser-delivered assets.
module PricingProxy
  TIMEOUT_SECONDS = 5
  ENDPOINT        = "/pricing-estimate"

  # Posts payload to <base>/pricing-estimate with the injected bearer secret.
  # @param payload [Hash] booking attributes to forward
  # @param base [String] scheme+host+port, e.g. "http://127.0.0.1:3007"
  # @return [Hash] with keys :status (Integer) and :body (Hash)
  def self.forward(payload, base:)
    secret = ENV.fetch("GAUNTLET_PRICING_SECRET", "")
    uri    = URI.parse("#{base}#{ENDPOINT}")

    http              = Net::HTTP.new(uri.host, uri.port)
    http.use_ssl      = uri.scheme == "https" # else an https base sends cleartext to :443
    http.open_timeout = TIMEOUT_SECONDS
    http.read_timeout = TIMEOUT_SECONDS

    req = Net::HTTP::Post.new(uri.request_uri)
    req["Authorization"]  = "Bearer #{secret}"
    req["Content-Type"]   = "application/json"
    req.body              = payload.to_json

    resp = http.request(req)
    { status: resp.code.to_i, body: JSON.parse(resp.body) }
  rescue Errno::ECONNREFUSED, Errno::ECONNRESET, Net::OpenTimeout, Net::ReadTimeout
    { status: 503, body: { error: "inference unavailable" } }
  rescue JSON::ParserError
    { status: 502, body: { error: "invalid upstream response" } }
  end
end

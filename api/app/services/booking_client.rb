# frozen_string_literal: true

# BookingClient — signs and POSTs a booking hash to the HouseAccount booking API.
# Mirrors the HMAC recipe in integration/sign_and_post.py (UTF-8 key, ts.body payload).
# Gated by BOOKING_LIVE=1; returns a simulated result when the gate is off.
require "net/http"
require "openssl"
require "uri"

module BookingClient
  BOOKINGS_URL    = "#{ENV.fetch('HOUSEACCOUNT_BASE', 'https://pro.houseparty.dev')}/api/bookings"
  TIMEOUT_SECONDS = 5
  SIMULATED       = { live: false, status: 0, body: "simulated (BOOKING_LIVE off)" }.freeze

  # Posts booking_hash to HouseAccount when BOOKING_LIVE=1; simulates otherwise.
  # @param booking_hash [Hash] fully-built booking attributes
  # @return [Hash] keys: :live (Boolean), :status (Integer), :body (String)
  def self.send_booking(booking_hash)
    return SIMULATED unless ENV["BOOKING_LIVE"] == "1" || BookingConfig.live?

    body = booking_hash.to_json
    ts   = Time.now.to_i.to_s
    key  = ENV.fetch("HOUSEACCOUNT_SIGNING_KEY", "")
    sig  = OpenSSL::HMAC.hexdigest("SHA256", key, "#{ts}.#{body}")
    hdrs = {
      "Content-Type"  => "application/json",
      "App-Name"      => ENV.fetch("HOUSEACCOUNT_APP_NAME", "gauntlet"),
      "App-Timestamp" => ts,
      "App-Signature" => sig
    }
    uri  = URI.parse(BOOKINGS_URL)
    http = Net::HTTP.new(uri.host, uri.port)
    http.use_ssl = uri.scheme == "https"
    http.open_timeout = TIMEOUT_SECONDS
    http.read_timeout = TIMEOUT_SECONDS
    req      = Net::HTTP::Post.new(uri.request_uri, hdrs)
    req.body = body
    resp     = http.request(req)
    { live: true, status: resp.code.to_i, body: resp.body.to_s }
  rescue StandardError => err
    { live: true, status: 0, body: "send failed: #{err.message}" }
  end

  # Build + send + record a conversion (source "api") for auto-send wiring.
  def self.auto_send(payload, result)
    sent = send_booking BookingBuilder.build(payload, result)
    ConversionStore.record_send(source: "api", payload: payload, result: result, sent: sent)
    sent
  end
end

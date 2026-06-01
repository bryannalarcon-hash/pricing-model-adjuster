# frozen_string_literal: true

# BookingController — thin CRUD surface for booking sends and conversion history.
# POST /dashboard/booking: build + send + record a conversion.
# GET  /dashboard/conversions: return stored conversions, newest first.
# GET/POST /dashboard/config: read or update the api_auto_send flag.
class BookingController < ApplicationController
  # @return [void]
  def create
    raw     = JSON.parse(request.raw_post)
    result  = raw["result"] || {}
    booking = BookingBuilder.build(raw["payload"] || {}, result)
    sent    = BookingClient.send_booking(booking)
    entry   = ConversionStore.record_send(source: raw["source"] || "manual",
                                          payload: raw["payload"] || {}, result: result, sent: sent)
    render json: { ok: true, live: sent[:live], status: sent[:status], conversion: entry }
  rescue JSON::ParserError
    render json: { error: "Malformed JSON" }, status: :bad_request
  end

  # @return [void]
  def index
    render json: ConversionStore.all
  end

  # @return [void]
  def config
    render json: { api_auto_send: BookingConfig.api_auto_send? }
  end

  # @return [void]
  def config_update
    raw = JSON.parse(request.raw_post)
    BookingConfig.set(raw["api_auto_send"])
    render json: { api_auto_send: BookingConfig.api_auto_send? }
  rescue JSON::ParserError
    render json: { error: "Malformed JSON" }, status: :bad_request
  end
end

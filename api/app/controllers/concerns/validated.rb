# frozen_string_literal: true

# Validated parses the JSON request body and enforces required-field presence
# on a controller. Rejects with 400 on malformed JSON or missing fields.
module Validated
  extend ActiveSupport::Concern

  REQUIRED_FIELDS = %w[job_id service_category zip_code job_description].freeze

  PERMITTED_FIELDS = %w[
    job_id service_category zip_code job_description
    service_subtype deadline booking_month job_status
    original_estimate original_estimate_lo original_estimate_hi
  ].freeze

  included do
    before_action :parse_json_body
    before_action :validate_required_fields
  end

  private

  def parse_json_body
    @parsed_body = JSON.parse request.body.read
  rescue JSON::ParserError
    render json: { error: "Malformed JSON" }, status: :bad_request
  end

  def validate_required_fields
    REQUIRED_FIELDS.each do |field|
      value = @parsed_body[field]
      next unless value.nil? || (value.respond_to?(:strip) && value.strip.empty?)

      render json: { error: "#{field} required" }, status: :bad_request
      return
    end
  end

  def booking_params
    @booking_params ||= @parsed_body.slice(*PERMITTED_FIELDS)
  end
end

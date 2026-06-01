# frozen_string_literal: true

# BookingBuilder — constructs the HouseAccount booking hash from a pricing result.
# Mirrors build_booking() in integration/sign_and_post.py; handles both string
# and symbol keys on the result hash (sidecar may return either).
module BookingBuilder
  COMMENT = "Synthetic test booking from the Gauntlet pricing-model integration. " \
            "Safe to delete."

  # Builds a tagged, disposable booking hash from raw payload and inference result.
  # @param payload [Hash] request booking params (string keys: zip_code, etc.)
  # @param result [Hash] inference result — string or symbol keys
  # @return [Hash] booking hash ready for BookingClient.send_booking
  def self.build(payload, result)
    res        = normalised(result)
    desc       = (payload["job_description"] || payload[:job_description] ||
                  "home service job").to_s
    midpoint   = res[:estimate_midpoint].to_f
    confidence = res[:confidence].to_f
    version    = res.fetch(:model_version, "gauntlet-v2.1.0")
    zip        = (payload["zip_code"] || payload[:zip_code] || "78704").to_s
    {
      "name"          => "Gauntlet Test",
      "phone"         => "5555550100",
      "zip"           => zip,
      "summary"       => "[GAUNTLET TEST] #{desc[0, 400]}",
      "comment"       => COMMENT,
      "deadline"      => payload["deadline"] || payload[:deadline] || "I'm flexible",
      "estimate"      => { "min" => res[:estimate_lo].to_f, "max" => res[:estimate_hi].to_f },
      "coverage"      => res.fetch(:coverage, ""),
      "uncertainties" => res.fetch(:uncertainties, ""),
      "confirmation"  => "Estimated $#{midpoint.round(0).to_i} " \
                         "(confidence #{confidence.round(2)}) by #{version}.",
      "campaign"      => { "utm_source" => "gauntlet-test", "utm_campaign" => "pricing-model" }
    }
  end

  # Normalises a result hash to symbol keys for uniform access.
  # @param result [Hash] may have string or symbol keys
  # @return [Hash] symbol-keyed copy
  def self.normalised(result)
    result.transform_keys(&:to_sym)
  end
  private_class_method :normalised
end

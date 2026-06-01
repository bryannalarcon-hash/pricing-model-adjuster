# frozen_string_literal: true

# BookingConfig — persists the api_auto_send toggle to data/booking_config.json.
# Path overridable via ENV["BOOKING_CONFIG_PATH"] for test isolation.
# All reads/writes rescue to false/no-op so a missing file is never fatal.
require "json"
require "fileutils"

module BookingConfig
  DEFAULT_PATH = Rails.root.join("..", "data", "booking_config.json")

  # Returns whether the API auto-send flag is enabled.
  # @return [Boolean]
  def self.api_auto_send?
    data = JSON.parse(File.read(config_path))
    data.fetch("api_auto_send", false) == true
  rescue StandardError
    false
  end

  # Persists the api_auto_send flag.
  # @param enabled [Boolean]
  # @return [void]
  def self.set(enabled)
    FileUtils.mkdir_p File.dirname(config_path)
    File.write(config_path, { api_auto_send: enabled == true }.to_json)
  rescue StandardError
    nil
  end

  # Returns the resolved file path (honours ENV override for test isolation).
  # @return [Pathname]
  def self.config_path
    Pathname.new(ENV.fetch("BOOKING_CONFIG_PATH", DEFAULT_PATH.to_s))
  end
  private_class_method :config_path
end

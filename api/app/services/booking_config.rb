# frozen_string_literal: true

# BookingConfig — persists booking toggles to data/booking_config.json:
#   api_auto_send (auto-send direct /pricing-estimate API calls), website_auto_send
#   (auto-send /dashboard/predict website requests), and live (really POST to staging
#   vs simulate). ENV["BOOKING_CONFIG_PATH"] overrides the path for tests. Reads rescue
#   to false; a missing file is never fatal.
require "json"
require "fileutils"

module BookingConfig
  DEFAULT_PATH = Rails.root.join("..", "data", "booking_config.json")

  # @return [Boolean] auto-send direct /pricing-estimate (API) calls
  def self.api_auto_send? = flag("api_auto_send")
  # @return [Boolean] auto-send website requests hitting /dashboard/predict
  def self.website_auto_send? = flag("website_auto_send")
  # @return [Boolean] sends really POST to staging (vs simulate)
  def self.live? = flag("live")

  # Merges the given flags into the stored config, preserving the others.
  # @param attrs [Hash] any of api_auto_send / website_auto_send / live => Boolean
  # @return [void]
  def self.update(attrs)
    clean = attrs.transform_keys(&:to_s).transform_values { |value| value == true }
    FileUtils.mkdir_p File.dirname(config_path)
    File.write(config_path, read.merge(clean).to_json)
  rescue StandardError
    nil
  end

  def self.flag(key) = read.fetch(key, false) == true
  private_class_method :flag

  def self.read
    JSON.parse(File.read(config_path))
  rescue StandardError
    {}
  end
  private_class_method :read

  def self.config_path
    Pathname.new(ENV.fetch("BOOKING_CONFIG_PATH", DEFAULT_PATH.to_s))
  end
  private_class_method :config_path
end

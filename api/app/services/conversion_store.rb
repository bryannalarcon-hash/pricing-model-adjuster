# frozen_string_literal: true

# ConversionStore — append-only JSONL log of booking conversion attempts.
# Persists to data/conversions.jsonl (repo-root-relative). Path overridable
# via ENV["CONVERSION_STORE_PATH"] for test isolation.
require "json"
require "fileutils"

module ConversionStore
  DEFAULT_PATH = Rails.root.join("..", "data", "conversions.jsonl")
  DEFAULT_LIMIT = 200

  # Appends a timestamped entry to the JSONL store.
  # @param entry_hash [Hash] fields: source, job_id, category, midpoint,
  #   confidence, live, status, summary (caller-supplied)
  # @return [Hash] the stored entry (with :recorded_at stamp)
  def self.record(entry_hash)
    stamped = entry_hash.merge(recorded_at: Time.now.utc.iso8601)
    FileUtils.mkdir_p File.dirname(store_path)
    File.open(store_path, "a") { |file| file.puts stamped.to_json }
    stamped
  end

  # Builds a conversion entry from a completed send and records it.
  # @return [Hash] the stored entry
  def self.record_send(source:, payload:, result:, sent:)
    res = result.transform_keys(&:to_sym)
    record(source: source, job_id: payload["job_id"],
           category: payload["service_category"], midpoint: res[:estimate_midpoint],
           confidence: res[:confidence], live: sent[:live], status: sent[:status],
           summary: payload["job_description"].to_s[0, 120])
  end

  # Returns the most recent entries, newest first.
  # @param limit [Integer] maximum number of entries to return
  # @return [Array<Hash>] parsed entries, newest first
  def self.all(limit = DEFAULT_LIMIT)
    lines = File.readlines(store_path, chomp: true)
    lines.last(limit).reverse.map { |line| JSON.parse(line) }
  rescue Errno::ENOENT, Errno::EACCES
    []
  end

  # Returns the resolved file path (honours ENV override for test isolation).
  # @return [Pathname]
  def self.store_path
    Pathname.new(ENV.fetch("CONVERSION_STORE_PATH", DEFAULT_PATH.to_s))
  end
  private_class_method :store_path
end

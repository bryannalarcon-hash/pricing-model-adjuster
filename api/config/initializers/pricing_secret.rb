# Enforce GAUNTLET_PRICING_SECRET is set at boot time.
# Mirrors receive-homeowner.js:20-22 boot-time enforcement pattern.
unless Rails.env.test?
  secret_missing = ENV["GAUNTLET_PRICING_SECRET"].blank?
  raise "GAUNTLET_PRICING_SECRET environment variable must be set" if secret_missing
end

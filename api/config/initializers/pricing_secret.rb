# Enforce that GAUNTLET_PRICING_SECRET is set at boot time.
# Mirrors receive-homeowner.js:20-22 boot-time enforcement pattern.
unless Rails.env.test?
  raise "GAUNTLET_PRICING_SECRET environment variable must be set" if ENV["GAUNTLET_PRICING_SECRET"].blank?
end

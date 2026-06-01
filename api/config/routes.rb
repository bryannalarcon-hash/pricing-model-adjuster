Rails.application.routes.draw do
  # Health check
  get "up" => "rails/health#show", as: :rails_health_check

  # Primary pricing endpoint
  match "/pricing-estimate",
        to: "pricing_estimate#create",
        via: :all

  # Netlify functions alias — same controller action
  match "/.netlify/functions/pricing-estimate",
        to: "pricing_estimate#create",
        via: :all

  # Dashboard SPA shell (U3) — redirect to the trailing-slash static path so the
  # browser renders index.html (and relative assets resolve) instead of downloading it
  get "/" => redirect("/dashboard/")
  get "/dashboard" => redirect("/dashboard/")

  # Dashboard JSON routes (U4)
  post "/dashboard/predict"     => "dashboard#predict"
  get  "/dashboard/metrics"     => "dashboard#metrics"
  get  "/dashboard/predictions" => "dashboard#predictions"

  # Booking + conversion + config routes
  post "/dashboard/booking"     => "booking#create"
  get  "/dashboard/conversions" => "booking#index"
  get  "/dashboard/config"      => "booking#config"
  post "/dashboard/config"      => "booking#config_update"
end

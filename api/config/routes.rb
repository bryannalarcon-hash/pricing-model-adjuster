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

  # Dashboard SPA shell (U3)
  get "/" => "dashboard#index"
  get "/dashboard" => "dashboard#index"

  # Dashboard JSON routes (U4)
  post "/dashboard/predict"     => "dashboard#predict"
  get  "/dashboard/metrics"     => "dashboard#metrics"
  get  "/dashboard/predictions" => "dashboard#predictions"
end

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
end

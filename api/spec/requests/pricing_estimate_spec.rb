require "rails_helper"
require "webmock/rspec"

RSpec.describe "POST /pricing-estimate", type: :request do
  let(:secret)  { "test-secret-value" }
  let(:headers) { { "Authorization" => "Bearer #{secret}", "Content-Type" => "application/json" } }

  let(:valid_payload) do
    {
      job_id:           "abc123",
      service_category: "Plumbing",
      zip_code:         "78704",
      job_description:  "Replace kitchen faucet"
    }
  end

  let(:sidecar_response) do
    {
      estimate_lo:       120.0,
      estimate_hi:       200.0,
      estimate_midpoint: 160.0,
      confidence:        0.82,
      model_version:     "gauntlet-v1.0.0",
      uncertainties:     "high distance from training distribution"
    }
  end

  before do
    # Reset the in-memory rate-limit store so request counts don't leak across examples
    Throttled.reset!

    # Set the secret so auth passes
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with("GAUNTLET_PRICING_SECRET", "").and_return(secret)

    # Stub the sidecar so tests don't need a running Python process
    stub_request(:post, /8011\/infer/)
      .to_return(
        status: 200,
        body: sidecar_response.to_json,
        headers: { "Content-Type" => "application/json" }
      )
  end

  # -----------------------------------------------------------------------
  # Happy path
  # -----------------------------------------------------------------------
  describe "happy path" do
    it "returns 200 with the correct response shape" do
      post "/pricing-estimate", params: valid_payload.to_json, headers: headers

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body["ok"]).to be true
      expect(body["job_id"]).to eq("abc123")
      expect(body["estimate_lo"]).to eq(120.0)
      expect(body["estimate_hi"]).to eq(200.0)
      expect(body["estimate_midpoint"]).to eq(160.0)
      expect(body["confidence"]).to eq(0.82)
      expect(body["model_version"]).to eq("gauntlet-v1.0.0")
      expect(body["uncertainties"]).to eq("high distance from training distribution")
    end

    it "forwards optional fields to the sidecar" do
      payload = valid_payload.merge(
        service_subtype:      "Water Heater",
        deadline:             "Within 1-2 weeks",
        booking_month:        "2026-05",
        original_estimate:    1850,
        original_estimate_lo: 1400,
        original_estimate_hi: 2300
      )

      post "/pricing-estimate", params: payload.to_json, headers: headers

      expect(response).to have_http_status(:ok)
      expect(WebMock).to have_requested(:post, /8011\/infer/)
        .with { |req| JSON.parse(req.body).key?("service_subtype") }
    end
  end

  # -----------------------------------------------------------------------
  # Alias path
  # -----------------------------------------------------------------------
  describe "alias path /.netlify/functions/pricing-estimate" do
    it "returns 200 on the alias path" do
      post "/.netlify/functions/pricing-estimate",
           params: valid_payload.to_json,
           headers: headers

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body["ok"]).to be true
    end
  end

  # -----------------------------------------------------------------------
  # Authentication
  # -----------------------------------------------------------------------
  describe "authentication" do
    it "returns 401 when the Authorization header is missing" do
      post "/pricing-estimate",
           params: valid_payload.to_json,
           headers: { "Content-Type" => "application/json" }

      expect(response).to have_http_status(:unauthorized)
      expect(JSON.parse(response.body)).to eq("error" => "Unauthorized")
    end

    it "returns 401 when the bearer token is wrong" do
      bad_headers = headers.merge("Authorization" => "Bearer wrong-token")
      post "/pricing-estimate", params: valid_payload.to_json, headers: bad_headers

      expect(response).to have_http_status(:unauthorized)
      expect(JSON.parse(response.body)).to eq("error" => "Unauthorized")
    end

    it "returns 401 when the Authorization header has no Bearer prefix" do
      bad_headers = headers.merge("Authorization" => secret)
      post "/pricing-estimate", params: valid_payload.to_json, headers: bad_headers

      expect(response).to have_http_status(:unauthorized)
      expect(JSON.parse(response.body)).to eq("error" => "Unauthorized")
    end
  end

  # -----------------------------------------------------------------------
  # Required field validation
  # -----------------------------------------------------------------------
  describe "required field validation" do
    %w[job_id service_category zip_code job_description].each do |field|
      it "returns 400 when #{field} is missing" do
        payload = valid_payload.except(field.to_sym).to_json
        post "/pricing-estimate", params: payload, headers: headers

        expect(response).to have_http_status(:bad_request)
        expect(JSON.parse(response.body)).to eq("error" => "#{field} required")
      end

      it "returns 400 when #{field} is blank" do
        payload = valid_payload.merge(field.to_sym => "").to_json
        post "/pricing-estimate", params: payload, headers: headers

        expect(response).to have_http_status(:bad_request)
        expect(JSON.parse(response.body)).to eq("error" => "#{field} required")
      end
    end
  end

  # -----------------------------------------------------------------------
  # Malformed JSON
  # -----------------------------------------------------------------------
  describe "malformed JSON" do
    it "returns 400 with Malformed JSON error" do
      post "/pricing-estimate",
           params: "{not valid json",
           headers: headers

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)).to eq("error" => "Malformed JSON")
    end
  end

  # -----------------------------------------------------------------------
  # Wrong HTTP method
  # -----------------------------------------------------------------------
  describe "wrong HTTP method" do
    it "returns 405 for GET" do
      get "/pricing-estimate", headers: headers

      expect(response).to have_http_status(:method_not_allowed)
      expect(JSON.parse(response.body)).to eq("error" => "Method not allowed")
    end

    it "returns 405 for PUT" do
      put "/pricing-estimate", params: valid_payload.to_json, headers: headers

      expect(response).to have_http_status(:method_not_allowed)
      expect(JSON.parse(response.body)).to eq("error" => "Method not allowed")
    end

    it "returns 405 for DELETE" do
      delete "/pricing-estimate", headers: headers

      expect(response).to have_http_status(:method_not_allowed)
      expect(JSON.parse(response.body)).to eq("error" => "Method not allowed")
    end
  end

  # -----------------------------------------------------------------------
  # Rate limiting (429, Appendix A optional)
  # -----------------------------------------------------------------------
  describe "rate limiting" do
    before do
      allow(ENV).to receive(:fetch).with("RATE_LIMIT_MAX", "60").and_return("2")
    end

    it "returns 429 with the Appendix A body and Retry-After header once over the limit" do
      3.times { post "/pricing-estimate", params: valid_payload.to_json, headers: headers }

      expect(response).to have_http_status(:too_many_requests)
      expect(JSON.parse(response.body)).to eq(
        "error" => "Rate limit exceeded", "retry_after" => 60
      )
      expect(response.headers["Retry-After"]).to eq("60")
    end

    it "allows requests up to the limit" do
      2.times { post "/pricing-estimate", params: valid_payload.to_json, headers: headers }

      expect(response).to have_http_status(:ok)
    end
  end

  # -----------------------------------------------------------------------
  # Sidecar failure
  # -----------------------------------------------------------------------
  describe "sidecar unavailable" do
    it "returns 500 with inference unavailable when sidecar is down" do
      stub_request(:post, /8011\/infer/).to_raise(Errno::ECONNREFUSED)

      post "/pricing-estimate", params: valid_payload.to_json, headers: headers

      expect(response).to have_http_status(:internal_server_error)
      expect(JSON.parse(response.body)).to eq("error" => "inference unavailable")
    end

    it "returns 500 when sidecar times out" do
      stub_request(:post, /8011\/infer/).to_timeout

      post "/pricing-estimate", params: valid_payload.to_json, headers: headers

      expect(response).to have_http_status(:internal_server_error)
      expect(JSON.parse(response.body)).to eq("error" => "inference unavailable")
    end

    it "returns 500 when sidecar returns a non-200 status" do
      stub_request(:post, /8011\/infer/)
        .to_return(status: 503, body: "service unavailable")

      post "/pricing-estimate", params: valid_payload.to_json, headers: headers

      expect(response).to have_http_status(:internal_server_error)
      expect(JSON.parse(response.body)["error"]).to be_present
    end
  end
end

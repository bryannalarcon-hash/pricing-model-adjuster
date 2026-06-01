# frozen_string_literal: true

# Spec for BookingController (POST /dashboard/booking, GET /dashboard/conversions,
# GET/POST /dashboard/config) and the auto-send wiring in PricingEstimateController.
# Never hits real staging: relies on BOOKING_LIVE default-off + WebMock.
require "rails_helper"
require "webmock/rspec"

RSpec.describe "Booking routes", type: :request do
  let(:json_headers) { { "Content-Type" => "application/json" } }

  let(:valid_payload) do
    {
      payload: {
        job_id: "test-001", service_category: "Plumbing",
        zip_code: "78704", job_description: "Replace kitchen faucet"
      },
      result: {
        estimate_lo: 120.0, estimate_hi: 200.0,
        estimate_midpoint: 160.0, confidence: 0.82,
        model_version: "gauntlet-v2.1.0", uncertainties: "low"
      },
      source: "website"
    }
  end

  let(:tmp_store)  { Tempfile.new(["conversions", ".jsonl"]).path }
  let(:tmp_config) { Tempfile.new(["booking_config", ".json"]).path }

  before do
    FileUtils.rm_f(tmp_store)
    FileUtils.rm_f(tmp_config)
    stub_const("ENV", ENV.to_h.merge(
      "CONVERSION_STORE_PATH" => tmp_store,
      "BOOKING_CONFIG_PATH"   => tmp_config
    ))
  end

  after do
    FileUtils.rm_f(tmp_store)
    FileUtils.rm_f(tmp_config)
  end

  # -----------------------------------------------------------------------
  # POST /dashboard/booking — BOOKING_LIVE unset (simulated)
  # -----------------------------------------------------------------------
  describe "POST /dashboard/booking (simulated, BOOKING_LIVE off)" do
    it "returns 200 with live:false and records a conversion" do
      post "/dashboard/booking", params: valid_payload.to_json, headers: json_headers

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body["ok"]).to be true
      expect(body["live"]).to be false
      expect(body["conversion"]).to include("source" => "website", "job_id" => "test-001")

      get "/dashboard/conversions"
      entries = JSON.parse(response.body)
      expect(entries).to be_an(Array)
      expect(entries.first).to include("job_id" => "test-001")
    end
  end

  # -----------------------------------------------------------------------
  # POST /dashboard/booking — BOOKING_LIVE=1 (WebMock stub)
  # -----------------------------------------------------------------------
  describe "POST /dashboard/booking (live, BOOKING_LIVE=1)" do
    before do
      stub_const("ENV", ENV.to_h.merge(
        "BOOKING_LIVE"          => "1",
        "HOUSEACCOUNT_SIGNING_KEY" => "test-key",
        "HOUSEACCOUNT_APP_NAME" => "gauntlet",
        "CONVERSION_STORE_PATH" => tmp_store,
        "BOOKING_CONFIG_PATH"   => tmp_config
      ))
      stub_request(:post, /pro\.houseparty\.dev\/api\/bookings/)
        .to_return(status: 201, body: { id: "bk-999" }.to_json,
                   headers: { "Content-Type" => "application/json" })
    end

    it "sends HMAC headers and returns live:true" do
      post "/dashboard/booking", params: valid_payload.to_json, headers: json_headers

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body["live"]).to be true
      expect(body["status"]).to eq(201)

      expect(WebMock).to have_requested(:post, /pro\.houseparty\.dev\/api\/bookings/)
        .with { |req|
          req.headers["App-Signature"].present? &&
          req.headers["App-Name"] == "gauntlet" &&
          req.headers["App-Timestamp"].present?
        }
    end

    it "marks a rejected live send as failed (non-2xx -> ok:false)" do
      stub_request(:post, /pro\.houseparty\.dev\/api\/bookings/)
        .to_return(status: 401, body: "unauthorized")

      post "/dashboard/booking", params: valid_payload.to_json, headers: json_headers

      body = JSON.parse(response.body)
      expect(body["live"]).to be true
      expect(body["status"]).to eq(401)
      expect(body["ok"]).to be false   # the SEND failed, even though the request was handled
      expect(body["conversion"]).to include("status" => 401, "live" => true)
    end
  end

  # -----------------------------------------------------------------------
  # GET /dashboard/config default; POST sets; GET reflects
  # -----------------------------------------------------------------------
  describe "config flag" do
    it "defaults to false" do
      get "/dashboard/config"
      expect(JSON.parse(response.body)["api_auto_send"]).to be false
    end

    it "persists true after POST and reflects in GET" do
      post "/dashboard/config",
           params: { api_auto_send: true }.to_json, headers: json_headers
      expect(JSON.parse(response.body)["api_auto_send"]).to be true

      get "/dashboard/config"
      expect(JSON.parse(response.body)["api_auto_send"]).to be true
    end

    it "defaults live to false and persists live independently" do
      get "/dashboard/config"
      expect(JSON.parse(response.body)["live"]).to be false

      post "/dashboard/config", params: { live: true }.to_json, headers: json_headers
      body = JSON.parse(response.body)
      expect(body["live"]).to be true
      expect(body["api_auto_send"]).to be false
    end

    it "makes a send live when the live flag is on (BOOKING_LIVE unset)" do
      stub_const("ENV", ENV.to_h.merge(
        "HOUSEACCOUNT_SIGNING_KEY" => "test-key", "HOUSEACCOUNT_APP_NAME" => "gauntlet",
        "CONVERSION_STORE_PATH" => tmp_store, "BOOKING_CONFIG_PATH" => tmp_config
      ))
      BookingConfig.update("live" => true)
      stub_request(:post, /pro\.houseparty\.dev\/api\/bookings/)
        .to_return(status: 201, body: "{}")

      post "/dashboard/booking",
           params: { source: "manual", payload: { job_id: "lv", service_category: "Cleaning",
                     zip_code: "75062", job_description: "x" },
                     result: { estimate_lo: 1, estimate_hi: 2, estimate_midpoint: 1.5,
                               confidence: 0.7 } }.to_json,
           headers: json_headers
      expect(JSON.parse(response.body)["live"]).to be true
      expect(WebMock).to have_requested(:post, /pro\.houseparty\.dev\/api\/bookings/)
    end
  end

  # -----------------------------------------------------------------------
  # Auto-send: POST /pricing-estimate triggers a conversion with source "api"
  # -----------------------------------------------------------------------
  describe "auto-send via POST /pricing-estimate" do
    let(:auth_secret) { "test-secret-value" }
    let(:auth_headers) do
      { "Authorization" => "Bearer #{auth_secret}", "Content-Type" => "application/json" }
    end
    let(:estimate_payload) do
      { job_id: "api-001", service_category: "Plumbing",
        zip_code: "78704", job_description: "Fix pipe" }
    end
    let(:sidecar_response) do
      { estimate_lo: 100.0, estimate_hi: 180.0, estimate_midpoint: 140.0,
        confidence: 0.75, model_version: "gauntlet-v2.1.0", uncertainties: "low" }
    end

    before do
      Throttled.reset!
      stub_const("ENV", ENV.to_h.merge(
        "GAUNTLET_PRICING_SECRET" => auth_secret,
        "CONVERSION_STORE_PATH"   => tmp_store,
        "BOOKING_CONFIG_PATH"     => tmp_config
      ))
      stub_request(:post, /8011\/infer/)
        .to_return(status: 200, body: sidecar_response.to_json,
                   headers: { "Content-Type" => "application/json" })

      # Enable auto-send
      BookingConfig.update("api_auto_send" => true)

      # Run Thread.new blocks synchronously for deterministic assertions
      allow(Thread).to receive(:new) { |&blk| blk.call; double("thread") }
    end

    it "records a conversion with source 'api'" do
      post "/pricing-estimate",
           params: estimate_payload.to_json, headers: auth_headers

      expect(response).to have_http_status(:ok)

      get "/dashboard/conversions"
      entries = JSON.parse(response.body)
      api_entry = entries.find { |e| e["source"] == "api" }
      expect(api_entry).not_to be_nil
      expect(api_entry["job_id"]).to eq("api-001")
      expect(api_entry["live"]).to be false   # live OFF -> programmatic send simulated
    end

    it "sends the programmatic auto-send LIVE when live mode is on" do
      stub_const("ENV", ENV.to_h.merge(
        "GAUNTLET_PRICING_SECRET" => auth_secret, "HOUSEACCOUNT_SIGNING_KEY" => "test-key",
        "HOUSEACCOUNT_APP_NAME" => "gauntlet",
        "CONVERSION_STORE_PATH" => tmp_store, "BOOKING_CONFIG_PATH" => tmp_config
      ))
      BookingConfig.update("api_auto_send" => true, "live" => true)
      stub_request(:post, /8011\/infer/)
        .to_return(status: 200, body: sidecar_response.to_json,
                   headers: { "Content-Type" => "application/json" })
      stub_request(:post, /pro\.houseparty\.dev\/api\/bookings/).to_return(status: 201, body: "{}")

      post "/pricing-estimate", params: estimate_payload.to_json, headers: auth_headers

      expect(WebMock).to have_requested(:post, /pro\.houseparty\.dev\/api\/bookings/)
      get "/dashboard/conversions"
      api_entry = JSON.parse(response.body).find { |e| e["source"] == "api" }
      expect(api_entry["live"]).to be true   # live ON -> programmatic send is real
    end
  end
end

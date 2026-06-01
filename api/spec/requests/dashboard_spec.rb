require "rails_helper"
require "webmock/rspec"

RSpec.describe "Dashboard routes", type: :request do
  let(:secret) { "demo-test-secret" }

  let(:upstream_ok) do
    {
      ok:                true,
      job_id:            "abc123",
      estimate_lo:       110.0,
      estimate_hi:       195.0,
      estimate_midpoint: 150.0,
      confidence:        0.79,
      model_version:     "gauntlet-v2.1.0",
      uncertainties:     "low distance from training distribution",
      coverage:          0.83
    }
  end

  before do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with("GAUNTLET_PRICING_SECRET", "").and_return(secret)
  end

  # -----------------------------------------------------------------------
  # POST /dashboard/predict — happy path
  # -----------------------------------------------------------------------
  describe "POST /dashboard/predict" do
    let(:payload) do
      { job_id: "abc123", service_category: "Plumbing",
        zip_code: "78704", job_description: "Replace faucet" }
    end

    before do
      stub_request(:post, /pricing-estimate/)
        .to_return(status: 200, body: upstream_ok.to_json,
                   headers: { "Content-Type" => "application/json" })
    end

    it "returns 200 with the Appendix A body including uncertainties" do
      post "/dashboard/predict", params: payload.to_json,
           headers: { "Content-Type" => "application/json" }

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body["estimate_lo"]).to eq(110.0)
      expect(body["uncertainties"]).to eq("low distance from training distribution")
      expect(body["coverage"]).to eq(0.83)
    end

    it "forwards the Authorization Bearer header" do
      post "/dashboard/predict", params: payload.to_json,
           headers: { "Content-Type" => "application/json" }

      expect(WebMock).to have_requested(:post, /pricing-estimate/)
        .with(headers: { "Authorization" => "Bearer #{secret}" })
    end

    it "passes through an upstream 400 with same status and body" do
      stub_request(:post, /pricing-estimate/)
        .to_return(status: 400, body: { error: "zip_code required" }.to_json,
                   headers: { "Content-Type" => "application/json" })

      post "/dashboard/predict", params: {}.to_json,
           headers: { "Content-Type" => "application/json" }

      expect(response).to have_http_status(400)
      expect(JSON.parse(response.body)["error"]).to eq("zip_code required")
    end

    it "passes through an upstream 401 with same status and body" do
      stub_request(:post, /pricing-estimate/)
        .to_return(status: 401, body: { error: "Unauthorized" }.to_json,
                   headers: { "Content-Type" => "application/json" })

      post "/dashboard/predict", params: payload.to_json,
           headers: { "Content-Type" => "application/json" }

      expect(response).to have_http_status(401)
      expect(JSON.parse(response.body)["error"]).to eq("Unauthorized")
    end
  end

  # -----------------------------------------------------------------------
  # GET /dashboard/metrics
  # -----------------------------------------------------------------------
  describe "GET /dashboard/metrics" do
    let(:metrics) do
      { blended: 10.47, real_only: 26.58, coverage: 0.83,
        baseline_blended: 14.2, baseline_real: 31.0, n_real: 120,
        model_version: "gauntlet-v2.1.0" }
    end

    it "returns parsed JSON when eval_metrics.json is present" do
      metrics_path = Rails.root.join("..", "reports", "eval_metrics.json")
      allow(File).to receive(:read).and_call_original
      allow(File).to receive(:read).with(metrics_path).and_return(metrics.to_json)

      get "/dashboard/metrics"

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body["blended"]).to eq(10.47)
      expect(body["coverage"]).to eq(0.83)
    end

    it "returns 503 when eval_metrics.json is absent" do
      metrics_path = Rails.root.join("..", "reports", "eval_metrics.json")
      allow(File).to receive(:read).and_call_original
      allow(File).to receive(:read).with(metrics_path).and_raise(Errno::ENOENT)

      get "/dashboard/metrics"

      expect(response).to have_http_status(:service_unavailable)
      expect(JSON.parse(response.body)["error"]).to eq("metrics unavailable")
    end
  end

  # -----------------------------------------------------------------------
  # GET /dashboard/predictions
  # -----------------------------------------------------------------------
  describe "GET /dashboard/predictions" do
    it "returns an array of prediction rows" do
      get "/dashboard/predictions"

      expect(response).to have_http_status(:ok)
      rows = JSON.parse(response.body)
      expect(rows).to be_an(Array)
      expect(rows.first).to have_key("estimate_midpoint")
      expect(rows.first).to have_key("confidence")
    end

    it "returns 503 when predictions.csv is absent" do
      csv_path = Rails.root.join("..", "predictions", "predictions.csv")
      allow(CSV).to receive(:read).and_call_original
      allow(CSV).to receive(:read).with(csv_path, headers: true).and_raise(Errno::ENOENT)

      get "/dashboard/predictions"

      expect(response).to have_http_status(:service_unavailable)
      expect(JSON.parse(response.body)["error"]).to eq("predictions unavailable")
    end
  end

  # -----------------------------------------------------------------------
  # Deployment self-containment — Railway builds the rails image from api/
  # only (rootDirectory=/api), so repo-root reports/ + predictions/ are NOT
  # in the container. Without in-context copies, metrics + predictions 503
  # and the SPA shows "API offline". Regression for that live failure.
  # -----------------------------------------------------------------------
  describe "in-image dashboard data (build context = api/)" do
    it "ships eval_metrics.json + predictions.csv inside api/" do
      expect(File).to exist(Rails.root.join("dashboard_data", "eval_metrics.json"))
      expect(File).to exist(Rails.root.join("dashboard_data", "predictions.csv"))
    end

    it "serves both from the in-context copy when repo-root outputs are absent" do
      m_legacy = DashboardController::METRICS_PATHS.first
      p_legacy = DashboardController::PREDICTIONS_PATHS.first
      allow(File).to receive(:exist?).and_call_original
      allow(File).to receive(:exist?).with(m_legacy).and_return(false)
      allow(File).to receive(:exist?).with(p_legacy).and_return(false)

      get "/dashboard/metrics"
      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to include("model_version")

      get "/dashboard/predictions"
      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body).first).to have_key("estimate_midpoint")
    end
  end
end

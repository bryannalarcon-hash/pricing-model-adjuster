# Load .env from project root (one level above the api/ directory) in development.
if defined?(Dotenv) && (Rails.env.development? || Rails.env.test?)
  root_env = Rails.root.join("..", ".env").expand_path
  Dotenv.load(root_env) if root_env.exist?
end

# syntax = docker/dockerfile:1

# Rails 7.1 API + dashboard SPA image (Railway "rails" service). Multi-stage:
# the build stage installs gems and bootsnap-precompiles; the final stage runs
# the server on $PORT. Upgrades RubyGems + pins bundler so Ruby 3.0's `tsort`
# default gem resolves to the locked 0.2.0 (else every `bundle exec` aborts).

# Make sure RUBY_VERSION matches the Ruby version in .ruby-version and Gemfile
ARG RUBY_VERSION=3.0.2
FROM registry.docker.com/library/ruby:$RUBY_VERSION-slim as base

# Rails app lives here
WORKDIR /rails

# Set production environment
ENV RAILS_ENV="production" \
    BUNDLE_DEPLOYMENT="1" \
    BUNDLE_PATH="/usr/local/bundle" \
    BUNDLE_WITHOUT="development"

# The ruby:3.0.2-slim base ships RubyGems 3.2.22, which pre-activates the `tsort`
# default gem (0.1.0) before Bundler can load the locked 0.2.0 that railties 7.1
# requires — aborting every `bundle exec` on Ruby 3.0 ("already activated tsort
# 0.1.0"). RubyGems 3.3.5 fixes that default-gem activation order. Also pin bundler
# to the lockfile's 2.5.23. Both go in the base stage so build and runtime inherit them.
RUN gem update --system 3.3.5 --no-document && \
    gem install bundler:2.5.23


# Throw-away build stage to reduce size of final image
FROM base as build

# Install packages needed to build gems
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y build-essential git pkg-config

# Install application gems
COPY Gemfile Gemfile.lock ./
RUN bundle install && \
    rm -rf ~/.bundle/ "${BUNDLE_PATH}"/ruby/*/cache "${BUNDLE_PATH}"/ruby/*/bundler/gems/*/.git && \
    bundle exec bootsnap precompile --gemfile

# Copy application code
COPY . .

# Precompile bootsnap code for faster boot times
RUN bundle exec bootsnap precompile app/ lib/


# Final stage for app image
FROM base

# Install packages needed for deployment
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y curl && \
    rm -rf /var/lib/apt/lists /var/cache/apt/archives

# Copy built artifacts: gems, application
COPY --from=build /usr/local/bundle /usr/local/bundle
COPY --from=build /rails /rails

# Run and own only the runtime files as a non-root user for security.
# Create log/ and tmp/ first: `railway up` uploads only git-tracked files, and the
# empty log/.keep + tmp/.keep dirs aren't tracked, so they're absent from the build
# context. mkdir keeps the chown (and puma's pidfile writes) working everywhere.
RUN useradd rails --create-home --shell /bin/bash && \
    mkdir -p log tmp tmp/pids && \
    chown -R rails:rails log tmp
USER rails:rails

# Entrypoint prepares the database.
ENTRYPOINT ["/rails/bin/docker-entrypoint"]

# Start the server by default, this can be overwritten at runtime
EXPOSE 3000
CMD ["./bin/rails", "server"]

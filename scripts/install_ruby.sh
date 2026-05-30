#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
PW="$(grep '^SUDO_PASSWORD=' .env | cut -d= -f2-)"
echo "[install] apt update..."
echo "$PW" | sudo -S -k DEBIAN_FRONTEND=noninteractive apt-get update -y
echo "[install] installing ruby-full + build deps..."
echo "$PW" | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ruby-full build-essential libssl-dev libyaml-dev zlib1g-dev libffi-dev \
  libreadline-dev libsqlite3-dev sqlite3 pkg-config git curl
echo "[install] ruby: $(ruby --version)"
export GEM_HOME="$HOME/.gem"; export PATH="$HOME/.gem/bin:$PATH"
gem install --no-document bundler rails
echo "[install] rails: $(rails --version 2>&1)"
echo "[install] DONE"

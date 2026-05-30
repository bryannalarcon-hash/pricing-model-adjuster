#!/usr/bin/env bash
export GEM_HOME="$HOME/.gem"; export PATH="$HOME/.gem/bin:$PATH"
cd "$(dirname "$0")/../api"
exec bin/rails server -p 3007 -b 127.0.0.1

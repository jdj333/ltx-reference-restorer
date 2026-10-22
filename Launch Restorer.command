#!/usr/bin/env bash
# macOS Finder entry point; settings can also be supplied through the terminal.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec "$repo_dir/scripts/launch.sh"

#!/usr/bin/env bash
# Start a source checkout. This installs locked application dependencies only;
# it never installs system packages, model weights or a ComfyUI backend.
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$repo_dir"

missing=0
for tool in uv node npm ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Missing prerequisite: %s\n' "$tool" >&2
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  printf '\nInstall uv, Node.js 22+ (including npm), and FFmpeg/ffprobe first.\n' >&2
  printf 'On macOS with Homebrew: brew install uv node ffmpeg\n' >&2
  printf 'See docs/setup.md for supported platforms and manual setup.\n' >&2
  exit 1
fi

node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
case "$node_major" in
  ''|*[!0-9]*)
    printf 'Cannot determine the Node.js major version. Install Node.js 22+.\n' >&2
    exit 1
    ;;
esac
if [ "$node_major" -lt 22 ]; then
  printf 'Node.js 22+ is required; found %s.\n' "$(node --version)" >&2
  exit 1
fi

printf 'Preparing LTX Reference Restorer from the locked checkout...\n'
printf 'Dependencies may be downloaded. Model weights and ComfyUI are not installed.\n'
uv sync --locked
(
  cd -- "$repo_dir/frontend"
  npm ci
  npm run build
)
printf '\nStarting the local API and render worker. Ctrl-C stops both.\n'
printf 'The default URL is http://127.0.0.1:8787; configuration can override it.\n'
printf 'FFmpeg baseline is available without model weights. LTX needs your configured backend.\n'
exec uv run --locked restorer start

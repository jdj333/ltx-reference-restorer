# Contributing

Start with the [setup guide](docs/setup.md), [architecture](docs/architecture.md), [verification and limits](docs/verification.md), and [integration contract](docs/integration-notes.md). This is an early local application. Preserve the source performance, original media and prior render versions; generated detail remains a review candidate.

## Run the checks

From a clone with Python, uv, Node.js and FFmpeg/ffprobe installed:

```sh
uv sync --locked --extra dev --extra public-demo
uv run pytest -q
cd frontend
npm ci
npm run build
npx playwright install chromium webkit
npm run test:e2e
```

The optional downloader is installed for an offline formatter regression test. The Python suite generates small local media and mocks network transport; it does not download films or weights. The browser suite starts an isolated temporary application/worker and uses generated test media. It does not reuse a server or normal project directory. Browser installation downloads test browser binaries; on a minimal Linux machine, Playwright may require its documented system dependencies. No films or model weights are downloaded by these tests. Results and screenshots are local ignored artifacts; CI retains synthetic browser failure artifacts for seven days. Use the committed lockfiles and include required lockfile changes with dependency updates.

The current local polish run passed 120 Python tests, the production build and six browser cases (three scenarios in both Chromium and WebKit). These are dated evidence, not a replacement for rerunning checks after a change. See [verification](docs/verification.md) for platform and CI scope.

For a manual workflow, return to the repository root and use a fresh ignored directory:

```sh
RESTORER_DATA_DIR="$PWD/.data/contribution-demo" uv run restorer demo
RESTORER_DATA_DIR="$PWD/.data/contribution-demo" uv run restorer start
```

Stop that directory's application/worker before creating or rerunning fixtures. Do not delete a worker lock or kill another process to bypass ownership. Use a fresh directory or identify the owning application first.

## Scope and evidence

Keep changes focused and include checks that exercise meaningful behavior. Rendering changes should preserve frame count/timestamps, display aspect, source/audio provenance, immutable submission snapshots, cancellation and retry ownership. A mocked backend test must remain labeled mocked. A successful doctor result is preflight, not inference. Do not add a success claim without the actual backend output and technical checks.

For UI work, check keyboard navigation, input labels, dialog focus/escape behavior, unsaved edits, empty/error/loading states and source/output comparison. Use synthetic media or the [public-film fixtures](docs/public-film-demo.md) for screenshots and reproducible reports.

## Report a bug safely

Use the repository's bug-report form. Give the commit/tag, operating system/architecture, relevant tool versions, exact UI steps, expected/actual behavior and whether the backend was FFmpeg or a real configured LTX workflow. Reproduce with the synthetic demo or name a public fixture and its recipe when possible.

Reports are public. Keep private footage, faces, project names, local usernames/paths, tokens, cookies, model weights, databases, raw doctor output, raw render logs and complete provenance local. Summarize a relevant error after removing personal paths and credentials. Crop screenshots to the public example. Use **Setup & status → Download safe diagnostics** for a report that excludes local paths/project contents, or share the public-demo safe JSON report for a public fixture. Inspect any attachment before posting. Maintainers do not need a copy of your entire application data directory.

## Pull requests

Explain the concrete trigger and resulting behavior, list executed checks and material limits, and update user documentation when behavior changes. Include source attribution for new public fixtures and document any preparation recipe. Never commit downloaded films, generated videos, app data, credentials or model weights. Preserve independent model/media license terms; a code change does not grant rights to those assets.

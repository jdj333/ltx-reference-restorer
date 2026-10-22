# Changelog

Changes are recorded by release. This application is a preview; successful conventional rendering does not establish LTX inference or historical fidelity.

## Unreleased

- Add a local readiness view for tools, worker heartbeat, storage and exact ComfyUI blockers, plus an in-app synthetic demo and safe diagnostics.
- Add scoped video/image browsing, visual native-pixel cropping, accessible dialogs and unsaved shot-setup guards.
- Add an isolated Chromium/WebKit browser regression suite and a locked source-checkout launcher for terminal or macOS Finder use.
- Reconcile dated verification evidence, public-film measurements, CI runs and platform limits.
- Add a first-use setup guide, contribution instructions, safe bug-report forms and a review checklist.
- Document the prerequisites and evidence required for a real controlled LTX pilot.
- Pass 120 local Python tests, the strict frontend build and six real Chromium/WebKit browser cases; rerun all three public-film baselines successfully. Expanded CI covers Python 3.11/3.14 and real Chromium/WebKit workflows; see [Actions](https://github.com/jdj333/ltx-reference-restorer/actions) for the matching commit's result.
- Prepare draft `v0.1.0-preview.1` notes; publication and code-license choice remain pending.

## Initial preview foundation — 2026-10-21

- Local FastAPI/SQLite workspace with actor references, shots, native-size reference placement guides, versioned render jobs and human review.
- Real FFmpeg baseline rendering, explicit media-integrity checks, source-audio handling, immutable snapshots, cancellation, retry and worker ownership.
- Synchronized side-by-side/overlay browser comparison and public-film workflow screenshots.
- Explicit ComfyUI Restore/Refine workflow contracts with pinned upstream provenance. Actual LTX inference remains unverified; missing prerequisites are reported as blockers.
- Reproducible acquisition and preparation recipes for three official Library of Congress YouTube editions, three real 49-frame baseline workflows and a safe machine-readable results report.
- 103 passing Python tests and production frontend build at `ed1fa38`, with successful GitHub Actions runs for the foundation and screenshot revisions. See [verification](docs/verification.md) for exact evidence and current limits.

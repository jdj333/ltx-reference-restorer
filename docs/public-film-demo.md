# Reproduce the public-film demonstration

This kit downloads three public institutional film uploads, prepares short documented fixtures, and exercises the wrapper with its real render worker. It keeps the downloaded editions intact and stores every derivative separately. The recipes, source catalog, runner, and selected reports are committed; media, local databases, render logs, and model weights remain outside Git.

See [executed results](public-film-results.md), the [machine-readable results](../fixtures/public-films/results/2026-10-21.json), and the separate [LTX backend preflight](public-demo-backend-status.md). Automated tests and mocked backend responses do not establish model inference or human approval of restoration quality.

## Sources and scope

The [source catalog](../fixtures/public-films/catalog.json) identifies these official Library of Congress YouTube uploads and the corresponding institutional archive records:

| Film | YouTube edition | Archive record | Fixture purpose |
| --- | --- | --- | --- |
| *St. Louis Blues* (1929) | [Library of Congress upload](https://www.youtube.com/watch?v=hdoRQ2iqh8I) | [Item 2023602002](https://www.loc.gov/item/2023602002/) | Face detail, expression and singing |
| *The Hitch-Hiker* (1953) | [Library of Congress upload](https://www.youtube.com/watch?v=VcKZ636kvxg) | [Item 2023602025](https://www.loc.gov/item/2023602025/) | Dialogue, gaze and modest head movement |
| *The Great Train Robbery* (1903) | [Library of Congress upload](https://www.youtube.com/watch?v=In3mRDX0uqk) | [Item 00694220](https://www.loc.gov/item/00694220/) | Early-film image damage and the final closeup |

The Library lists all three in its [public-domain film selection](https://www.loc.gov/free-to-use/public-domain-films-from-the-national-film-registry/). The catalog records that assessment's United States scope and the specific editions. It does not cover unrelated uploads, later colorizations, replacement music, or other additions. Credit: Library of Congress, Motion Picture, Broadcasting, and Recorded Sound Division.

The observed YouTube downloads totaled **633,137,963 bytes, approximately 604 MiB**. All were 24 fps and 720 pixels high; *St. Louis Blues* was 960 × 720, and the other two were 1280 × 720. These are downloaded viewing editions, not a claim about original film capture timing or scan quality. Any supplied soundtrack is treated as edition audio; the 1903 film's audio stream is not evidence of an original synchronized soundtrack.

## Download and prepare

Install the repository's normal prerequisites: Python 3.11–3.14, uv, FFmpeg/ffprobe, and Node.js 22+ for the browser frontend. Run these commands from the repository root:

```sh
uv sync --locked --extra dev --extra public-demo
uv run restorer public-fetch
uv run restorer public-prepare
```

`public-fetch` defaults to YouTube and uses the official uploads in the catalog. The `public-demo` extra installs its downloader. It records the actual provider, canonical source URL, edition, acquisition time, size, SHA-256, and tool versions in each `acquisition.json`. A subsequent fetch verifies and reuses a complete matching acquisition; an incomplete or changed acquisition is preserved and rejected. Downloads do not use account cookies or credentials and do not silently switch providers.

The catalog also identifies Library of Congress archive alternatives. The committed shot recipes target the inspected **YouTube editions**; archive timing and framing are not interchangeable with those recipes. An archive download is recorded as an archive download.

By default, downloaded files are stored under `.data/public-films/media/`. Preparation reads [selections.json](../fixtures/public-films/selections.json) and writes `.data/public-films/prepared/manifest.json` plus per-fixture assets and `preparation.json` records. The prepared directory must be empty: use a new `--output-dir` for another preparation version.

Each fixture contains **49 consecutive frames**, about 2.04 seconds at the downloaded rate. Preparation applies a documented 2× Lanczos downscale and H.264 encoding, retains supplied source audio through AAC encoding, and resets clip timestamps while recording the mapping to source frames and timestamps. It applies no denoising, sharpening, deinterlacing, frame interpolation, or generated image detail. The unchanged higher-resolution download remains available locally as a comparison target for this controlled degradation experiment.

Each reference is an authentic, native-size crop from a frame **outside the evaluated shot**. Recipes record its source frame and crop in original source pixels; placement coordinates use the prepared clip's pixels. The preparer checks edition ID, duration, geometry, frame rate, progressive layout, held-out reference position, and prepared timing. Every prepared clip and reference has its own SHA-256.

YouTube can change its offered encodes, and FFmpeg versions can produce different derivative bytes. The local acquisition and preparation records retain the hashes of the files actually used; reproducing the recipe does not promise byte-identical downloads or encodes. A geometry, frame-rate, or duration mismatch stops preparation so the changed edition can be reviewed.

## Run the wrapper workflow

Run with the application and worker stopped for the selected test data directory:

```sh
uv run restorer public-demo
```

This defaults to a **fresh** `.data/public-films/app` directory and the baseline backend. It never uses the ordinary application project directory. The runner refuses a database with existing records and acquires the same single-worker lock as normal rendering.

For each fixture it:

1. Imports the clip, verifies its hash, creates a project, shot and actor, and imports the reference as pending.
2. Checks that a pending reference cannot enter a guide, then approves the reference explicitly for automated fixture setup and prepares a static guide.
3. Queues and processes a real FFmpeg baseline job, checking frame timing/count, duration, aspect ratio, and expected audio presence.
4. Stores a **Needs Revision** review and note labeled **AUTOMATED FIXTURE PERSISTENCE TEST ONLY**, then reopens the service to verify persistence.
5. Changes reference notes, creates and cancels a new version, retries and cancels that version, and verifies that the completed output, frozen reference snapshot, and original fixture bytes remain unchanged.

Baseline rendering does not consume the actor reference. Its guide is a placement/review aid. The automated review exercises storage and requires subsequent human comparison; it is not acceptance of identity, expression, mouth timing, motion, or historical fidelity. Audio-presence and timestamp checks also do not substitute for listening.

The safe report is written to `.data/public-films/app/demo/latest-public-demo.json` and printed as JSON. It includes render settings, source/clip/reference/output hashes, technical checks, job IDs, and local API asset URLs. It excludes raw import paths, backend errors, logs, and complete provenance. Exit status is **0** for a passed workflow, **1** for a failed workflow, and **2** when the requested LTX test is blocked.

Each repeat needs a new app directory. For example:

```sh
uv run restorer public-demo --data-dir .data/public-films/app-v2 --report .data/public-films/baseline-v2.json
```

Keep `--manifest` pointed at the intended prepared version when using custom preparation directories.

## Open the real results in the browser

Build the frontend once, then start the application using the same public-test data directory:

```sh
cd frontend
npm ci
npm run build
cd ..
RESTORER_DATA_DIR=.data/public-films/app RESTORER_PORT=8790 uv run restorer start
```

Open **http://127.0.0.1:8790**. Choose a public film project and inspect its completed baseline version. Compare the source and output with synchronized playback, scrubbing, overlay, and enlarged face regions. Inspect the reference and guide; evaluate expression, gaze, eyes, mouth movement, motion, flicker, background changes, and invented detail. Record a human review only after this comparison. Restart with the same data directory to confirm that your decision persists. Ctrl-C stops the server and its worker.

For public screenshots, show the public fixture comparison panels. Keep local health/doctor output, import fields, raw job logs, databases, and full provenance local: these can contain machine paths even though the shareable report omits them. Media and generated app data are ignored by Git. Share the catalog, recipes and safe reports so others can recreate their own local media.

## Request an actual LTX A/B/C comparison

Configure an existing compatible ComfyUI installation using [integration-notes.md](integration-notes.md) and the bundled Restore workflow. The required nodes and exact model files must be present. Set `RESTORER_CONFIG` to your local TOML file or set the documented environment variables; no command in this kit downloads weights or installs a backend.

```sh
uv run restorer doctor
uv run restorer public-demo --backend comfy_restore --data-dir .data/public-films/app-ltx --report .data/public-films/ltx-report.json
```

These commands use the configured backend. A clean doctor result establishes preflight eligibility; it does not establish inference. The LTX run requires another fresh app directory.

| Variant | Actual processing |
| --- | --- |
| A | FFmpeg Lanczos baseline upscale |
| B | Configured LTX workflow without actor-reference conditioning |
| C | Same frozen LTX source, prompt, seed, scale, steps and CFG, with one approved reference at a fixed placement |

B/C share the submission snapshot so edits cannot silently change their common inputs. LTX is reported completed only after the real worker obtains and validates its generated output. An unavailable backend or failed reference preflight still permits the actual A baseline test and produces an explicit blocker with exit status 2; it creates no substitute B/C result. A render failure remains a failure and has no success claim. `--backend comfy_refine` uses a compatible configured Refine Details workflow separately.

The initial conditioning path supports one actor and one selected reference at a fixed region. It does not demonstrate native simultaneous multi-reference identity conditioning. Compare B and C against the source after they actually complete; sharper texture alone does not establish better identity or preserved performance. Keep both unsuccessful and successful attempts in your review record.

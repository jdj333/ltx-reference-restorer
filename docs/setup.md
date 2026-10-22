# Setup and first use

The application runs locally from a source checkout. The conventional FFmpeg baseline, reference library, guides and comparison UI need no model weights. LTX Restore/Refine requires a separately installed, licensed and configured ComfyUI backend; the wrapper does not install it or download models.

## Supported and exercised platforms

The recorded end-user workflow was tested on **macOS arm64 (Apple M1 Max, 32 GB)**. The [verification matrix](verification.md) records exact Python/browser results and their revision scope, including the decoded-still paused-comparison path described below. Historical Ubuntu GitHub Actions runs passed the Python/FFmpeg suite and frontend build; that is narrower than a tested interactive desktop installation. The expanded CI matrix (Python 3.11/3.14 and a separate Chromium/WebKit job on Python 3.12/Node 22) is configured; check [Actions](https://github.com/jdj333/ltx-reference-restorer/actions) for each exact commit's result. Other Linux/macOS configurations need local verification. **Native Windows is unsupported** because the worker currently uses POSIX process/locking facilities. WSL has not been validated as a desktop installation. See the [verification matrix](verification.md#tested-platforms).

Install these prerequisites yourself:

| Tool | Requirement | Purpose |
| --- | --- | --- |
| Python | 3.11–3.14 allowed by the project | Backend; uv can select a compatible interpreter |
| [uv](https://docs.astral.sh/uv/) | Available on PATH | Locked Python environment and launcher |
| Node.js / npm | Node.js 22+ with npm | Build the browser interface |
| FFmpeg / ffprobe | Both available on PATH | Media probing, preparation, rendering and validation |

On macOS with Homebrew:

```sh
brew install uv node ffmpeg
```

This command is optional guidance; the application never runs a system package manager for you. Declared version ranges are not a claim that every combination has been tested.

## Launch a checkout

Clone the repository, then run:

```sh
git clone https://github.com/jdj333/ltx-reference-restorer.git
cd ltx-reference-restorer
./scripts/launch.sh
```

On macOS, you can also double-click **Launch Restorer.command** inside the checkout. The launcher checks uv, Node.js 22+, npm, FFmpeg and ffprobe; syncs the committed Python lock; installs the frontend npm lock; builds the UI; and starts the API and worker. Dependency installation may access the network. It does not install system tools, download models or start ComfyUI. A missing prerequisite stops with an explanation.

The launcher was exercised from a fresh checkout with spaces in its path, including a newly created Python 3.14.6 environment, frontend install/build, live API/worker and a successful unreviewed synthetic baseline. See the [recorded verification](verification.md#recorded-evidence).

Open **http://127.0.0.1:8787**. Select **Setup & status** to check tools, worker state, storage and exact ComfyUI blockers. The view distinguishes advertised model filenames from proven inference and offers **Download safe diagnostics** without paths/project contents/raw logs. The local storage path is displayed for your own use; omit it from public screenshots. Leave the launcher terminal open. **Ctrl-C stops this application's API and worker.** The launch command works when the checkout path contains spaces. Use a terminal for custom environment/configuration settings. If executable permissions were lost while extracting an archive, run `bash scripts/launch.sh` from its repository root.

The equivalent manual setup is:

```sh
uv sync --locked
cd frontend
npm ci
npm run build
cd ..
uv run --locked restorer doctor
uv run --locked restorer start
```

Developers should add `--extra dev --extra public-demo` to the sync command and follow [CONTRIBUTING.md](../CONTRIBUTING.md). No downloaded film is needed to try the synthetic demo.

## Start with isolated example data

Keep examples separate from real projects. Stop the example directory's application/worker before creating its demo, and run:

```sh
RESTORER_DATA_DIR="$PWD/.data/first-demo" uv run --locked restorer demo
RESTORER_DATA_DIR="$PWD/.data/first-demo" uv run --locked restorer start
```

Alternatively, with `restorer start` already running, choose **Try synthetic demo** from the welcome page or Setup & status. The in-app action queues the real baseline for the existing worker and reuses its labeled demo project on subsequent opens.

The synthetic demo creates procedural source media, a labeled generated reference, a shot, a guide and a real baseline output. It leaves the result unreviewed. Reopen the demo project in the browser and compare source/output, step frames, inspect the guide and save your review.

Paused comparison displays server-decoded PNG stills for the selected frame, using the completed job's frozen source/output mapping rather than the browser video element's most recently painted frame. Step controls and keyboard arrows change the still pair; side-by-side and overlay use those same decoded images. The app shows loading while the requested pair is being obtained and an explicit error if it cannot be verified/decoded. It hides the old pair and face crops while loading or failed, and offers **Retry exact frames** after a failure. Play switches to synchronized browser video playback; pausing returns to the selected decoded stills. Browser playback is useful for judging motion, while paused stills provide the exact frame comparison. Restart with the same data directory to reopen it. A baseline does not consume actor conditioning and does not establish restoration fidelity.

For real historical examples, follow the [public-film reproduction guide](public-film-demo.md). Its downloads are opt-in, attributed and kept outside Git; run its commands against fresh dedicated directories. Neither example workflow overwrites ordinary projects.

## Local data and import scope

The current default data directory on every platform is `~/Library/Application Support/LTX Reference Restorer`. On Linux, choose a suitable path explicitly. Set it consistently when starting both API and worker:

```sh
RESTORER_DATA_DIR="$PWD/.data/my-workspace" ./scripts/launch.sh
```

**Browse local videos/images** opens the scoped server-side file browser. Its roots come from `import_roots`; an advanced path field remains available. Image/source-frame reference previews offer a visual crop and native-pixel inputs. Save shot setup before navigating away; unsaved actor/reference/placement changes trigger a discard prompt.

The application copies imported source media into its data directory and records hashes. Copies, outputs, references, SQLite and review state belong together. To back up a workspace, stop its API/worker and copy the entire data directory. Keep originals and prior versions; a render is a separate candidate.

For scoped imports and backend settings, copy [config.example.toml](../config.example.toml) to an untracked local configuration, restrict `import_roots` to your intended media folders, and run:

```sh
RESTORER_CONFIG=/absolute/path/to/config.local.toml ./scripts/launch.sh
```

`RESTORER_DATA_DIR`, `RESTORER_HOST`, `RESTORER_PORT`, `RESTORER_COMFY_URL`, `RESTORER_COMFY_WORKFLOW`, `RESTORER_FFMPEG` and `RESTORER_FFPROBE` override their corresponding config settings. Relative paths resolve from the launcher's repository directory. Use absolute paths in a reusable configuration.

## Common setup problems

| Symptom | Action |
| --- | --- |
| Browser UI missing | Complete `npm ci` and `npm run build` in `frontend`, or rerun the launcher. |
| Port 8787 occupied | Start with `RESTORER_PORT=8790 ./scripts/launch.sh`, then open port 8790. Leave unrelated services running. |
| Imports denied | Add the resolved media directory to `import_roots` in your local config. The app intentionally refuses paths outside that scope. |
| Jobs stay queued | Use `restorer start` so both API and worker run, or start the dedicated worker with the same configuration/data directory. |
| Another worker owns this directory | Locate the existing application using that workspace. Do not remove its lock or start duplicate workers. |
| Paused comparison loading or failing | Wait for both requested stills. If an error appears, check that the completed job's source/output files are intact; a changed file or decode failure is refused. Keep the error visible rather than judging an earlier frame as the current one. |
| Interrupted render | Use retry for a new immutable version after the worker has recorded interruption. Partial denoising is not resumed. |
| ComfyUI unavailable or missing nodes/models | Read the [backend preflight](public-demo-backend-status.md) and [integration notes](integration-notes.md); install/configure the intended backend separately. A baseline does not substitute for a failed LTX job. |
| Rotation, VFR, interlace or reference constraints | Read the exact rejection, retain the original and prepare an explicit documented derivative only when needed. The app does not silently change performance timing. |

Keep the server bound to localhost. This is a trusted-user application without authentication for use as a public network service. Doctor, local paths, raw logs and full provenance may contain personal information; keep them local. Use a synthetic/public fixture and a sanitized error summary when [reporting a bug](../CONTRIBUTING.md#report-a-bug-safely).

## Code, film and model terms

The application code and original documentation use the [MIT License](../LICENSE). Third-party film editions and model files retain their own terms. Review the linked media provenance and official model access/license conditions separately; installing or running MIT-licensed wrapper code does not accept those conditions or grant access to gated weights.

# Verification and known limits

Last reconciled **2026-10-21**. This page separates completed checks from model-inference and human-review work. Test counts below describe the named revision or validation stage; they are not a claim that every later commit has run the same checks.

## Recorded evidence

| Revision / check | Result | Evidence and scope |
| --- | --- | --- |
| Initial application, `bf2fb3e` | 64 Python tests passed; TypeScript/Vite production build passed | Real FFmpeg synthetic application workflow plus isolated backend contract tests. [GitHub Actions run](https://github.com/jdj333/ltx-reference-restorer/actions/runs/39652892100) passed on Ubuntu. |
| Public-film kit, `ed1fa38` | **103 Python tests passed**; frontend build passed | Real YouTube acquisition, preparation, three actual public-film baseline runs and separate configured-LTX preflight. [Detailed results](public-film-results.md), [safe JSON report](../fixtures/public-films/results/2026-10-21.json), [GitHub Actions run](https://github.com/jdj333/ltx-reference-restorer/actions/runs/39686103086). |
| Screenshot documentation, `24c0795` | GitHub Actions passed | [Recorded run](https://github.com/jdj333/ltx-reference-restorer/actions/runs/39689908738); five captures of the real public-film browser workflow are in the README. |
| Preview polish, local validation | **120 Python tests passed** in 25.71 s; strict TypeScript/Vite build passed; **6 browser cases passed** in 17.0 s | Three scenarios in each of Playwright Chromium and WebKit against the actual isolated API/worker and real FFmpeg. All three 49-frame public-film baselines passed again; [fresh safe report](../fixtures/public-films/results/2026-10-21-polish.json). Local results only; check the matching commit in [Actions](https://github.com/jdj333/ltx-reference-restorer/actions) for remote CI. |
| Clean checkout of [`d547818`](https://github.com/jdj333/ltx-reference-restorer/commit/d5478184b03b9fd250968965d1b1f1f7819c57e5) | Locked launcher install, production build, API, worker and real synthetic baseline passed | Fresh virtual environment and frontend install in a checkout whose path contains spaces. uv selected Python 3.14.6 on macOS arm64. The 24-frame baseline passed timing/aspect checks, remained unreviewed, and reopened without a duplicate job. Ctrl-C stopped both owned processes; the checkout stayed clean. |

The three linked historical runs above were independently checked as completed/success. New commits have their own [Actions results](https://github.com/jdj333/ltx-reference-restorer/actions). An earlier run does not establish the status of a newer commit. CI uses synthetic/local test assets and isolated transport mocks; it does not download films, accept model access terms or run a GPU model.

The expanded CI configuration runs Python 3.11 and 3.14 checks plus a separate Python 3.12/Node 22 Chromium/WebKit job. The configuration alone does not establish a successful run. Consult [Actions](https://github.com/jdj333/ltx-reference-restorer/actions) for the result attached to the exact commit being evaluated.

## What the executed workflows establish

- The synthetic demo imported procedural media, prepared a generated reference and native-size guide, and produced a real 2× FFmpeg baseline. Its 24-frame, two-second output had zero measured video timestamp/duration discrepancy and retained audio. The command leaves the result unreviewed.
- The public-film runner downloaded the three catalogued Library of Congress YouTube editions and prepared three 49-frame clips. All three real baseline jobs passed frame-count, timestamp, duration, display-aspect and audio-presence checks. Source/clip/reference files remained unchanged. See [full measurements and their limits](public-film-results.md).
- Reference approval gates, guide placement, source/reference hashes, immutable job snapshots, cancellation, retry-as-new-version, worker locking and SQLite reopen are covered. Staged in-app demo recovery covers interruption before import, after database commit and after guide preparation, while preserving changed reference notes, source bytes, extra actors and human reviews. VFR timing, anamorphic aspect ratio, TFF/BFF field-aware scaling and delayed audio alignment have real FFmpeg coverage.
- Prepared-video padding/export tests use real FFmpeg. Passing prepared pixels through an isolated round trip establishes media handling, not model processing.
- ComfyUI contract tests use mocked transport, node schemas and model inventories to check graph inputs, controlled B/C differences, recipe constraints, errors, scoped cancellation and duplicate-submission prevention. Mock output is never an actual LTX result.
- Chrome displayed all three public projects, decoded source/output video, and exercised synchronized comparison, overlay, exact frame stepping, face regions, references, playback and saved review/notes. No browser warning/error was recorded during those checks. The fixture's Needs Revision review is an explicit automated persistence state, not a person's image-quality verdict.
- The six automated browser cases exercise real baseline processing, safe-diagnostics download, idempotent synthetic-demo opening, synchronized playback/frame stepping, keyboard and overlay comparison, saved review/reopen, scoped local video/image browsing, native-pixel reference cropping, approval, guide preparation and a manual-project render. Dialog focus/return, delayed-save disabled controls, unsaved-setup guards and project-draft isolation are exercised in both browser engines. These use generated media and actual local services; browser test scripts do not fabricate successful render responses. Playwright WebKit coverage is not acceptance testing of a particular Safari release.
- The launcher passes Bash syntax checks, stops for missing prerequisites and Node 20, and retains the exact locked sync/build/start sequence from a different working directory and a checkout path with spaces. The latter sequencing checks use fake prerequisite tools and do not claim another live server was started.
- `restorer start` runs the API and worker as separate supervised processes. Its supervisor stops its own children on Ctrl-C. Port conflicts are handled by selecting another port; unrelated services are left running.

The current 120-test run emitted one Starlette/httpx deprecation warning; assertions passed. Runtime measurements from these short FFmpeg clips are not an LTX benchmark. Process-memory sampling may be denied by macOS and is then recorded as unavailable.

## Tested platforms

| Platform | Verified | Not established |
| --- | --- | --- |
| macOS arm64, Apple M1 Max, 32 GB unified memory | Local setup, FFmpeg 8.0, Python 3.13.3, production browser build, synthetic/public-film baseline workflow, manual Chrome comparison and automated Playwright Chromium/WebKit workflows. A fresh launcher environment also passed on Python 3.14.6. | LTX model loading, MPS inference, model memory requirements, restoration fidelity or speed |
| Ubuntu GitHub Actions, Python 3.12 and Node 22 | Python suite, real FFmpeg tests and frontend production build at the linked historical revisions | Interactive desktop/browser acceptance or CUDA inference |
| Other macOS/Linux versions and hardware | No dedicated end-user installation run recorded | Compatibility and performance must be checked locally |
| Native Windows | Unsupported by the current POSIX worker lock and supervisor implementation | No native Windows installation or end-to-end support claim. WSL is a separate Linux environment and has not been validated as a desktop installation. |

Declared Python and Node version ranges are dependency constraints. They do not mean that every version/platform combination has been exercised.

## Still unverified

**No actual LTX model has been loaded or run by this application.** The freshly checked default ComfyUI endpoint refused connections; the inspected installation lacks the required LTX nodes and weight files. The configured public-film LTX runner produced passing A baselines and explicit B/C blockers, returning exit status 2. It submitted no B/C jobs. See the [dated backend preflight](public-demo-backend-status.md).

The supplied workflow graphs derive from pinned upstream executable code. Schema discovery, advertised model filenames and isolated tests establish eligibility for an attempted render, not model loading, weight integrity, hardware compatibility, runtime or image quality. Installed core/node revisions must be checked against the graph. No MLX restoration/reference backend is enabled.

Initial LTX conditioning supports one actor, one approved native crop, static placement and progressive CFR shots with 2–97 source frames, padded to an `8n+1` length between 9 and 97. Motion keyframes can assist guide review; moving-reference, multiple-actor, streaming-reference and long-shot conditioning remain unavailable.

Technical checks do not establish identity, original expression, gaze, mouth timing, motion, flicker, invented detail, historical fidelity or listening approval. Source audio is retained by content with AAC transcoding for prepared/baseline media; it is not a bit-identical audio archive. Display-rotation sources require an explicit documented derivative. Interlaced baselines preserve supported known field orders; LTX requires a progressive derivative.

## Recheck a checkout

Follow [setup](setup.md), then run the commands in [CONTRIBUTING.md](../CONTRIBUTING.md). Keep the synthetic or public-film test directory separate from normal projects. Record the exact commit, executed command and result when sharing verification. The next model milestone is a real baseline/B/C public-film pilot followed by a human comparison; the [pilot procedure](ltx-pilot.md) defines what must be retained.

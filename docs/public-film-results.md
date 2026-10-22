# Public film test results — 2026-10-21

**Three real public-film baseline workflows passed. No LTX inference was run.** The configured LTX comparison was attempted at preflight and blocked because the ComfyUI endpoint, nodes and model files were unavailable.

The initial kit evidence below belongs to `ed1fa38`. During preview polish, the suite grew to **120 Python tests** with **6 passing Chromium/WebKit browser cases**, and all three public-film baselines passed again. The [fresh polish report](../fixtures/public-films/results/2026-10-21-polish.json) retains that rerun; see [verification](verification.md) for current checks and CI scope.

These are actual local downloads and FFmpeg renders, not simulated model outputs. The [reproduction guide](public-film-demo.md), [source catalog](../fixtures/public-films/catalog.json), [exact shot recipes](../fixtures/public-films/selections.json), and [machine-readable results](../fixtures/public-films/results/2026-10-21.json) let others repeat the experiment without bundling films or generated videos in Git.

## Acquisition and prepared shots

All three films were retrieved from their official **Library of Congress YouTube uploads**, totaling 633,137,963 bytes (about 604 MiB). No archive alternative was used. Full downloads were retained unchanged, with SHA-256, provider/edition, size and tool versions in acquisition ledgers. The Library includes these titles in its [public-domain film selection](https://www.loc.gov/free-to-use/public-domain-films-from-the-national-film-registry/); the catalog records edition and United States rights scope.

| Fixture | Official YouTube | Target start / zero-based frame | Held-out reference | Prepared input → baseline output |
| --- | --- | --- | --- | --- |
| St. Louis Blues — singing | [hdoRQ2iqh8I](https://www.youtube.com/watch?v=hdoRQ2iqh8I) | 930 s / 22320 | 934 s / 22416 | 480×360 → 960×720 |
| The Hitch-Hiker — closeup | [VcKZ636kvxg](https://www.youtube.com/watch?v=VcKZ636kvxg) | 1199 s / 28776 | 1202 s / 28848 | 640×360 → 1280×720 |
| The Great Train Robbery — closeup | [In3mRDX0uqk](https://www.youtube.com/watch?v=In3mRDX0uqk) | 798 s / 19152 | 812 s / 19488 | 640×360 → 1280×720 |

Each target has 49 source frames at the edition's encoded 24 fps, lasting 2.041667 seconds. Preparation deliberately downsamples the downloaded picture by two with Lanczos before baseline upscaling; it does not add denoising, sharpening, deinterlacing, frame interpolation or generated detail. Source/derivative frame timestamps are mapped explicitly. The higher-resolution original download is a controlled-experiment comparison target, not an assertion of historical ground truth.

References are authentic native-pixel source crops outside each evaluated interval. Some are from the same continuous camera shot, so these examples are not an independent identity benchmark. The singer example includes a background performer; it tests a single assigned reference and does not establish multi-actor model support. The train shot includes a firearm. The audio stream is preserved from each supplied viewing edition; the 1903 film's stream is not evidence of an original synchronized soundtrack.

## Executed wrapper checks

For **all three fixtures**, actual imports, source/reference hashes, manual shot setup, pending-reference rejection, explicit fixture-only reference approval, native-crop guide preparation, queued worker processing, immutable versions, queued cancellation, retry-as-new-version, notes/review persistence, and reopening passed. The source/clip/reference files remained unchanged.

| Technical check | St. Louis Blues | The Hitch-Hiker | The Great Train Robbery |
| --- | --- | --- | --- |
| Expected / actual output frames | 49 / 49 | 49 / 49 | 49 / 49 |
| Maximum measured video timestamp difference | 0 ms | 0 ms | 0 ms |
| Measured duration difference | 0 ms | 0 ms | 0 ms |
| Display aspect-ratio difference | 0 | 0 | 0 |
| Supplied audio stream present | Yes | Yes | Yes |
| Baseline job state | Succeeded | Succeeded | Succeeded |
| Human identity/performance approval | Not performed | Not performed | Not performed |

The automated **Needs Revision** review is explicitly labeled a persistence test. It does not mean a person rejected image quality, and it is not acceptance of restoration fidelity. Audio presence and timing checks are not a listening evaluation or a bit-identical audio archive.

The configured Restore comparison was also exercised in a separate fresh application directory. It produced three actual A baselines with the same passing integrity checks and **three explicit LTX blockers**. No B/C job was submitted and no baseline was labeled LTX. That command returned exit status 2. See the [backend preflight](public-demo-backend-status.md) for the freshly observed installation and exact missing prerequisites.

## Browser and regression verification

Chrome opened all three public projects. Source/output video decoded and displayed side by side; overlay, frame stepping, enlarged face regions, selected references, saved test review/notes and playback controls were exercised. The train comparison reached its final displayed frame with zero reported playhead drift. Browser error/warning collection was empty during the check. This is UI verification, not human historical-fidelity approval.

The new acquisition command was verified with a fresh real YouTube download after an initial end-to-end check found a JSON-formatting bug in the yt-dlp output template. The fix is covered by a test using yt-dlp's actual template formatter. Other acquisition tests mock transport and do not download films in CI.

**103 tests passed**, including the existing real FFmpeg integration tests and new acquisition, preparation, source-frame mapping, edition mismatch, path isolation, public report, reference provenance, persistence and backend-blocker coverage. The TypeScript/Vite production build passed. One Starlette/httpx deprecation warning remains. CI installs the optional downloader for offline formatter coverage; it does not download films or model weights.

Test environment: macOS arm64, Python 3.13.3, FFmpeg 8.0, yt-dlp 2026.10.21. Observed runtime belongs to these small FFmpeg tests. It is not an LTX inference benchmark, and no model-memory or speed claim is inferred from system RAM.

## What remains

Install and configure the compatible ComfyUI/LTX nodes and licensed model files, run actual B/C inference, then review identity, eyes, mouth, expression, gaze, blinking, motion, flicker, background changes, invented detail and audio synchronization. The kit supports this next step but does not claim its outcome. Source timing, labels and review decisions must remain attached to their actual input/output hashes.

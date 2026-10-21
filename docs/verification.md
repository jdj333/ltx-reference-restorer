# Executed verification

Date: **2026-10-21**. Local macOS arm64, Python 3.13.3, FFmpeg/ffprobe 8.0 and Node 26.5.0. These observations describe this implementation run, not a benchmark for every target Mac.

## Passed

- `uv sync --locked --extra dev` resolved the committed Python lock; the browser has a committed npm lock.
- `pytest -q`: **64 tests passed**, including a real FFmpeg baseline application workflow, frame timestamp mapping, VFR timing, anamorphic aspect ratio, TFF/BFF field-aware scaling, delayed audio alignment, source/reference hashes, approval persistence, scoped files, coordinate transformations/native guide placement, cancellation, safe retry, restart recovery, one-worker locking and immutable versions.
- The media preparation/export test uses real FFmpeg to pad source geometry and tail frames, then removes that padding and restores source audio. Passing prepared video directly through this isolated test is **not model inference** and is not an application rendering backend.
- Isolated Comfy tests mock transport and node inventories: mapped API inputs, B/C graph differences, installed schema/model blockers, exact sampler recipe, error handling, scoped cancellation, and prevention of duplicate remote submissions. No mock output is represented as an actual LTX render.
- Controlled-comparison tests mock availability only to inspect frozen B/C submission snapshots. The jobs remain queued, with no generated video or inference success claim.
- `npm run build` passes strict TypeScript compilation and Vite production packaging.
- `restorer demo` generates procedural media, imports a shot and generated actor reference, prepares a native-crop guide and produces a real 2× FFmpeg baseline. The 24-frame, two-second result had zero measured video timestamp/duration discrepancy and retained source audio. The demo command leaves results unreviewed.
- `restorer doctor` reports macOS/arm64, memory/disk, tool versions, baseline availability, disconnected default ComfyUI, and unavailable MLX restoration/reference operations.
- Actual Chrome smoke check: built UI served by the API, source/output playback, three exact frame steps showing frame 03 on both sides at 0.25 seconds, zero paused playhead drift, selected generated-reference labeling, and an explicit synthetic test review saved and reopened. The test review note identifies it as an automated persistence check, not human approval of film fidelity.
- `restorer start` launches API and worker separately. Port 8787 was already occupied by another service; verification used port 8790. The supervisor stops its own children on Ctrl-C.

The test runner emits one Starlette/httpx deprecation warning; assertions pass. Lightweight CI is included. GitHub Actions had not run at the time of these implementation checks; check the repository's Actions tab for results after publication.

## Not established

- No actual LTX model was loaded or run. Default `http://127.0.0.1:8188` was disconnected and no Comfy workflow was configured for inference. The supplied API graphs were derived from pinned executable upstream code and are validated against installed schemas before use; runtime/hardware compatibility is still untested.
- No MLX restoration/reference backend is enabled. Image anchors do not establish the required spatial actor-reference operation.
- No speed or model-memory estimate for an M1 Max 32 GB, Mac Studio 36 GB, or M5 Max 128 GB is inferred from capacity. Worker CPU RSS observations may be unavailable under macOS process-inspection restrictions; the job records that limitation rather than failing the render.
- No original film or actor photograph was used. No synthetic review, technical test, or model result establishes historical fidelity or substitutes for a person's visual/listening review.
- Initial model conditioning supports one actor, one approved native crop, static placement, progressive CFR inputs and 2–97 source frames padded to 9–97. Motion keyframes are available for guide review/crops; moving reference conditioning, multiple actors, streaming references and long shots remain unavailable.
- Source audio content is retained, with AAC transcoding for prepared/baseline media; this is not bit-identical archival audio. Display-rotation sources require an explicit derivative. Interlaced baseline preserves known field orders and rejects unsupported layouts; LTX requires progressive sources.

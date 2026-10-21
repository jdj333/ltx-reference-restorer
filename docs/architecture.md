# Architecture

The source film supplies the performance. Approved references guide appearance and detail. The application records and presents evidence for human assessment; a successful process never certifies identity or motion fidelity.

## Processes and storage

The React/TypeScript interface talks to a localhost FastAPI server. The API owns project metadata, scoped imports, references, shot setup, guide previews and immutable render requests. A separate Python worker claims one queued job at a time from SQLite. `restorer start` launches the API and worker together; either process can also run separately. FFmpeg/ffprobe inspect media, extract frames, prepare clips, produce the conventional baseline and restore source audio to model output.

The configurable data directory contains `restorer.sqlite3`, imported source copies, references, previews, guides and versioned job directories. Original input files are read and copied, never edited. SHA-256 hashes bind media to its provenance. SQLite uses short transactions and WAL. An OS file lock in the data directory prevents multiple workers from claiming simultaneous renders. Completed job outputs remain in their original directory. Retry and changed settings create new jobs; an accepted version is not overwritten.

```text
Browser → localhost API → SQLite + managed media directory
                              ↑
                     separate worker (one job)
                       ↙                ↘
              FFmpeg baseline      existing ComfyUI
```

`backend/restorer/backends` keeps rendering engines separate from project logic. Backend capabilities and preflight reject unsupported requests before submission. The conventional backend is always labeled **baseline upscale** and does not condition on actor references. ComfyUI uses a configured API-format workflow bundle, explicit input bindings, node/model discovery, upload, prompt submission, progress/history and output retrieval. MLX restoration/reference operations remain unavailable until the exact required pipeline is ported and verified. Ingredients generation is outside the restoration backend.

## Time and geometry

Imported media is inspected for its actual frame timestamps, durations, rational frame rate, audio, pixel dimensions, sample aspect ratio and field order. A shot uses source time bounds and an explicit source-frame mapping. Variable frame rate is identified and handled explicitly; a generative workflow must not silently reinterpret it as constant rate. Frame interpolation, denoising and deinterlacing are not automatic preprocessing steps.

The baseline uses field-aware scaling and interlaced H.264 encoding for known top/bottom display-field order, preserving frame timestamps and field order. Unsupported or unknown interlacing cannot be silently normalized. Model workflows require progressive CFR inputs. Display-rotation metadata is rejected initially, preventing the decoder's automatic rotation from invalidating source-space face coordinates.

Placement keyframes use source pixel coordinates, never preview pixels. Browser preview coordinates are transformed back to the source grid. Linear or held interpolation is available for preparing guides; a backend may impose stricter movement restrictions. Guide placement records source, working canvas and padding transforms. The approved reference crop stays at native resolution and is centered on the transformed face region in the gray canvas; its pixels are not resized to match the drawn box. A crop that leaves the canvas is rejected. Model dimensions and frame counts are validated; padding and final trimming are recorded. Export preserves the intended aspect ratio, timing and source audio. Model-generated audio is not used as a replacement soundtrack.

## References and review

Named actors have multiple reference records with view, quality, approval, provenance, crop, source location, timestamp and content hashes. Approval and quality are independent. Generated reconstructions remain labeled generated after approval. Ranking is deterministic and explainable; selected references remain fixed in a job snapshot. A guide is a prepared conditioning artifact, not evidence of model acceptance or fidelity.

The first model-conditioned scope is one actor with a fixed placement in a short shot. Manual guide interpolation is useful for review, while unsupported moving or multiple-actor conditioning is rejected. The actual guide artifact is shown before rendering. No identity-lock control exists.

Review records accepted, rejected or needs-revision separately from technical state. Synchronized source/output playback, overlay, face regions, reference images, alignment data and notes support review. Identity, eyes, mouth, expression, gaze, motion, flicker and invented detail are human criteria. No synthetic accuracy percentage is reported.

## Failures and reproducibility

Jobs move through queued, running, succeeded, failed, canceled or interrupted. Cancellation stops the local subprocess or scoped ComfyUI prompt. Restart marks abandoned running work interrupted after worker ownership is established. Retry is a new version, not a claim of mid-render continuation. Partial files are not published as successful output.

Each job stores the source and reference hashes, shot/setup snapshot, guide, backend/workflow/model details, prompt, seed, supported controls, timing, dimensions, logs, errors and observed memory/runtime. Technical checks compare expected and produced media. This metadata aids reproduction but does not promise bit-identical output across hardware, engine versions or nondeterministic kernels.

## Local access

The app binds to `127.0.0.1` by default. Import paths must resolve inside configured import roots. Asset serving is confined to the managed data directory. Subprocesses use argument arrays without shell interpolation. This is a trusted-user desktop service; do not publish it to a network without adding authentication and a reviewed deployment boundary. Model weights, credentials, source films, output videos, caches and local databases are excluded from Git.

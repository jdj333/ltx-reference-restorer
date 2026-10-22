# First real LTX pilot

**Status: not run.** The public-film baseline workflows passed, but the inspected backend lacks the prerequisites for B/C inference. Follow this procedure only after an independently managed ComfyUI installation is ready and you have reviewed/obtained the required model access. No command below accepts model terms, downloads weights or provisions compute.

The aim is a small, inspectable comparison. The source supplies motion, timing, composition and expression. A reference guides appearance/detail; model output is a candidate for review, not historical evidence.

## Prerequisite evidence

1. Use an idle intended ComfyUI instance. Check its queue and this wrapper's active worker before submission; do not duplicate an existing render or interrupt unrelated work. Keep a single worker per application data directory.
2. Install the exact required LTX nodes and matching files described in [integration notes](integration-notes.md). Keep the selected node/core revisions, model filenames and SHA-256 values locally. Advertised filenames alone do not establish file integrity.
3. Review model terms and access conditions yourself using the official model pages. Do not include account tokens, cookies or gated files in a report. The [current local preflight](public-demo-backend-status.md) records why this installation could not proceed.
4. Record the actual hardware/accelerator, unified memory or VRAM, OS, Python/PyTorch/backend versions and available disk. Capacity alone does not establish that the graph will load or finish. Check any model/backend device requirements against your chosen installation.

## Prepare one public shot

First follow the [public-film download and preparation guide](public-film-demo.md). Retain the full acquisition ledgers and prepared frame maps. The following makes a **new manifest**, leaving the complete three-film manifest and media intact. Run from the repository root:

```sh
uv sync --locked --extra public-demo
uv run --locked restorer public-fetch
uv run --locked restorer public-prepare
uv run --locked python - <<'PY'
import json
from pathlib import Path
root = Path('.data/public-films/prepared')
source = root / 'manifest.json'
target = root / 'pilot-hitch-manifest.json'
manifest = json.loads(source.read_text())
manifest['fixtures'] = [f for f in manifest['fixtures'] if f['id'] == 'hitch-hiker-closeup']
if len(manifest['fixtures']) != 1:
    raise SystemExit('Expected exactly one reviewed Hitch-Hiker fixture')
with target.open('x') as stream:
    stream.write(json.dumps(manifest, indent=2) + '\n')
print(target)
PY
```

If acquisition/preparation already exists, use its verified edition and manifest rather than overwrite it. The new pilot manifest is in the same directory so its confined relative media paths remain valid; a second manifest-creation attempt stops instead of replacing an earlier recipe.

This first target is 49 progressive CFR frames, approximately 2.04 seconds at 24 fps, with one held-out authentic source crop and fixed placement. Its prepared picture is 640×360. The held-out native reference is 410×490, so scale 1 would not fit that crop on a 640×384 padded canvas. This recipe therefore uses **scale 2**: 1280×720 content on a 1280×736 padded canvas; export removes the explicit padding. The already checked public guide uses this geometry. A smaller first-loading probe needs a separately reviewed crop/recipe, rather than silently shrinking the native reference. Higher-scale or longer runs are separate experiments.

## Configure and check

Copy `config.example.toml` to a private untracked local file, keep localhost addresses unless you have independently secured a remote installation, and set `comfy_url` and the **absolute path** of `workflows/ltx25-restore.json`. Do not repurpose or change another application's backend. Keep this pilot's app directory fresh and stopped during the runner.

```sh
RESTORER_CONFIG=/absolute/path/to/config.local.toml uv run --locked restorer doctor
```

Keep raw doctor output local: it can contain paths and backend metadata. Confirm actual connectivity, node schemas, required model filenames, operation and reference support. A clean preflight permits an attempted render; it does not establish inference. Missing nodes/models or incompatible schemas should remain explicit blockers, without renaming incompatible files or substituting a baseline.

## Execute A/B/C

Choose a fresh `--data-dir` for every attempt. Preserve failures and their local records so changes can be explained. The runner controls the worker itself; do not run another worker for this directory while it executes.

```sh
RESTORER_CONFIG=/absolute/path/to/config.local.toml uv run --locked restorer public-demo \
  --manifest .data/public-films/prepared/pilot-hitch-manifest.json \
  --backend comfy_restore --scale 2 \
  --data-dir .data/public-films/pilot-hitch-01 \
  --report .data/public-films/pilot-hitch-01-report.json
```

| Variant | Processing | Shared evidence |
| --- | --- | --- |
| A | Actual FFmpeg Lanczos baseline | Same prepared source and target dimensions |
| B | Actual configured LTX Restore, without actor conditioning | Frozen source, prompt, seed, schedule, scale, steps, CFG and workflow |
| C | Same LTX Restore, with one approved reference in a fixed region | Same common B settings; only the actor-reference path is enabled |

Exit 0 means the requested technical workflow passed, 1 means failure, and 2 means blocked LTX prerequisites. A missing backend still allows an actual A baseline and records B/C as not completed. Treat output as LTX only after actual submission, processing, retrieval and media checks. The runner's fixture approval and Needs Revision note are automated persistence checks, not a person's quality judgment.

If a render fails or runs out of memory, retain its record, note the failure, and adjust only a documented new attempt. Do not infer that another machine, quantization or backend can perform the same operation merely because it can load an LTX model. Refine Details is a separate workflow/version and comes after a verified Restore pilot, rather than being silently chained.

## Collect technical and human evidence

Retain these locally for each real attempt:

| Evidence | Required record |
| --- | --- |
| Inputs | Canonical public source URL/edition; downloaded, prepared clip and reference SHA-256; selected source frames and timestamps; native reference crop and placement |
| Configuration | Application commit, actual core/node revisions, workflow and submitted graph hashes, model filenames/hashes, prompt, seed, sampler/sigma schedule, scale, frame count, canvas/padding and guide hash |
| Execution | Actual prompt/job IDs, backend state, elapsed runtime and measured memory where available; failures/cancellation and whether remote execution was confirmed stopped |
| Outputs | Actual output hashes, decoded frame count/timestamps, duration, display aspect, expected audio presence/alignment and technical-check results |
| Human review | Reviewer/date, exact compared output hashes, identity/expression/motion notes, visible failures and Accept/Reject/Needs Revision; listening status separately |

Open the same pilot directory only after the runner has finished:

```sh
RESTORER_CONFIG=/absolute/path/to/config.local.toml \
RESTORER_DATA_DIR=.data/public-films/pilot-hitch-01 RESTORER_PORT=8790 \
uv run --locked restorer start
```

Use synchronized side-by-side and overlay at full frame and the face region. Compare source/A, source/B and source/C, then B/C. Inspect eyes, blinking, mouth and speech timing, expression, gaze, head/body motion, hands, background changes, flicker and invented detail. References can affect pixels outside the selected region. Sharper texture alone is not better identity or preserved performance. Listen to retained edition audio and inspect synchronization; audio presence is insufficient.

Record a human decision only after reviewing the actual candidates. Keep an unsuccessful or uncertain comparison as such. A same-shot held-out crop is a useful setup exercise, not an independent multi-angle identity benchmark. Moving subjects, multiple actors and simultaneous multiple references require separate validated experiments.

For publication, inspect the safe public-demo JSON report and summarize actual hardware/runtime, graph/model identifiers, technical results and review limits. Keep raw logs, doctor output, signed URLs, credentials, machine paths, app databases, full provenance and model files local. Publish attributed public-example crops/comparisons only with their edition/rights scope and clear model-generated labeling. Update [verification](verification.md) only when the claimed step actually completed.

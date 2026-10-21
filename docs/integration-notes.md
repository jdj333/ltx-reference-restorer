# Rendering integration evidence

Retrieved **2026-10-21**. The source film supplies the performance; approved references guide appearance and detail. That is a review criterion, not a property this application can promise for generated frames.

## What has and has not been verified

This first version implements a complete conventional FFmpeg baseline workflow and a real ComfyUI HTTP adapter with explicit API graph mappings. The two bundled LTX graphs were derived from the actual upstream tiled workflow and checked against executable node source. Each submission also validates the installed server's `/object_info` input schemas, output slots, node availability, and advertised model filenames. The installed server performs its own `/prompt` validation.

**No actual LTX, CUDA/MPS or MLX model inference was run for this repository. The default configured ComfyUI endpoint was disconnected, and no model weights were downloaded or loaded. Other local installations and model caches were not inventoried. Identity retention, performance retention, model memory requirements and speed remain unmeasured.** A schema-compatible server is eligible for an attempted render; it is not proof the model will fit memory or finish. A job succeeds only after actual processing, output retrieval, and media integrity validation. Isolated HTTP/backend tests use mocks and are not inference tests.

The upstream UI workflow uses UUID subgraphs and `nodes`/`links`; it is not directly accepted by `/prompt`. `workflows/ltx25-restore.json` and `workflows/ltx25-refine.json` contain explicit flattened **API graphs in a mapping bundle**, not that UI JSON. The bundle's `status` and `upstream` fields identify the derivation and its untested status. They retain the local text-encoder, source-video IC-LoRA, distilled sigma schedule, fusion sampling, tiled decoding and save-video operations. They omit optional network prompt enhancement, audio generation, and the upstream streaming/audio-encode path. The worker supplies the prepared, padded source canvas. Original source audio is handled separately by FFmpeg.

## Inspected upstream versions

| Source | Retrieved revision | Evidence |
| --- | --- | --- |
| [Lightricks/LTX-2](https://github.com/Lightricks/LTX-2) | `e98f6d927d83c92ef2be6aec76c8440b19306e39` | [IC-LoRA pipeline](https://github.com/Lightricks/LTX-2/blob/e98f6d927d83c92ef2be6aec76c8440b19306e39/packages/ltx-pipelines/src/ltx_pipelines/ic_lora.py) |
| [Lightricks/ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) | `220e1d45aa0469f518e982102fca4dca92a61862` | [Guide and adapter implementation](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/220e1d45aa0469f518e982102fca4dca92a61862/iclora.py), [fusion sampler](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/220e1d45aa0469f518e982102fca4dca92a61862/tiled_fusion_sampler.py), [actual UI workflow](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/220e1d45aa0469f518e982102fca4dca92a61862/example_workflows/2.5/LTX-2.5_V2V_TiledFusion_Upscale.json) |
| [ComfyUI core](https://github.com/Comfy-Org/ComfyUI) | `d80736d2aa63d318bbe60417e75dd1d49d532eaf` | [HTTP routes](https://github.com/Comfy-Org/ComfyUI/blob/d80736d2aa63d318bbe60417e75dd1d49d532eaf/server.py), [video nodes](https://github.com/Comfy-Org/ComfyUI/blob/d80736d2aa63d318bbe60417e75dd1d49d532eaf/comfy_extras/nodes_video.py), [LTX nodes](https://github.com/Comfy-Org/ComfyUI/blob/d80736d2aa63d318bbe60417e75dd1d49d532eaf/comfy_extras/nodes_lt.py) |
| [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | `49b093a39c19169a8a81721dcc541e07e945232f` | Model card and file listing; gated `auto` |
| [Restore IC-LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Restore) | `ed04134f5512bca3f7f36118d36737da09569c35` | Model card and file listing; gated `auto` |
| [Refine Details IC-LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details) | `4912c478b35dd96b6cdcc5f7c7ff9d72c2c57929` | Model card and file listing; gated `auto` |
| [Ingredients IC-LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients) | `12040e4091ac2008d3906a594e31a7fb1ab9d546` | Model card and file listing; gated `auto` |
| [dgrauet/ltx-2-mlx](https://github.com/dgrauet/ltx-2-mlx) | `03597a9e5675b5e3b62b84856023c597b65c1c0a` | README, `docs/PIPELINES.md`, `docs/PIPELINE_MATURITY.md`, `ic_lora.py`, `utils/args.py` |

The revisions identify inspected code and remote repository metadata; they are **not installed or inference-tested versions**. Hugging Face exposed model cards and public file metadata while raw gated files required authorization. No gated weights were accessed. These API revisions do not attest the bytes of a user's installed model; the job records workflow/model names and workflow hashes, while doctor reports that local model hashes cannot be recovered from ComfyUI's standard object schema.

## Restore and Refine Details semantics

The Restore card describes a 2.3-trained adapter tested upstream on the 2.5 distilled transformer, 2.5 video VAE, and Gemma-4 encoder. Refine Details is based on 2.5. The reviewed files are `ltx-2.5-22b-ic-lora-restore-1.0.safetensors` and `ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors`. Both use the source video itself as a frame-aligned IC-LoRA control signal at latent downscale factor 1. Restore can infer color and reconstruct missing regions; Refine can invent fine texture. None of these details become historical evidence by being generated.

The working canvas is a multiple of 32 on each side; temporal lengths use `8n+1`. The app starts with 9–97 prepared frames, padding the final source frame explicitly and trimming the padding after rendering. It rejects VFR and interlaced sources for this LTX path instead of silently converting frame timing or deinterlacing. Baseline organization/review remains available. Source and canvas dimensions are mapped with aspect-preserving scale and padding; the canvas is not stretched into a new aspect ratio. No blanket denoise, sharpen or interpolation filter is applied.

The distilled recipe uses Euler, the exact eight-step schedule in the upstream workflow, adapter strength 1, trained tile 960×544 for Restore or 1024×576 for Refine, overlap 0.5 and blend variance 0.05. `LTXVTiledFusionSampler` shares a noise field and fuses tiles at every step; `LTXVTiledSampler` independently samples tiles and is a different operation. Restore should precede Refine when both are desired; this app creates separate immutable job versions rather than automatically chaining them.

Neither adapter was trained for audio generation. The adapter returns a silent visual render, and the worker restores the original shot audio. The app does not replace speech with model audio.

## Spatial actor reference conditioning

The model cards document an optional second `LTXAddVideoICLoRAGuide` after the video guide with `frame_idx=-1`, strength 1, downscale factor 1, and `use_streaming=false`. Its image is a grey canvas of the output dimensions with subject crops placed over their own subjects. The fusion sampler crops guide metadata and pixels to each spatial tile. A reference pasted elsewhere influences the wrong tiles; a generic portrait or I2V starting keyframe is not an equivalent actor reference.

Executable `LTXAddVideoICLoRAGuide.resolve_frame_idx` explicitly preserves negative values as RoPE positions **before** the clip, rather than resolving them from the last video frame. This resolves the apparent conflict with generic keyframe APIs. The streaming branch requires `frame_idx=0`, factor 1, fresh per-window guides, and disables tiled VAE guide encoding. A static -1 reference therefore uses the whole-clip path, with sampler `tile_frames=0`. The first version deliberately does not enable long streaming shots with actor references.

The app uses RGB `(128,128,128)` as a documented neutral grey convention; upstream specifies grey without a numeric value. Placement metadata records source coordinates, aspect scale, padding, actual paste dimensions and conditioning-image hash. The preview displays the actual artifact sent to ComfyUI. The initial scope is one approved reference and one actor at a static placement; multiple differing placement keyframes and multi-actor conditioning are rejected with an explanation. Manual interpolation remains useful for review overlays, but is not a moving-reference model capability. There is no identity-lock operation or accuracy percentage.

For the controlled B/C comparison, the same source, model, adapter, seed, prompt, sigma schedule, dimensions and frame count are retained. The reference-enabled graph adds the reference image loader and second -1 guide. The B graph removes those nodes and reconnects sampler conditioning/latent inputs directly to the source-video guide. A reference can influence pixels beyond the marked face, and final acceptance requires human review of identity, expressions, gaze and movement.

## Model files and configuration

Downloads must be explicit and user initiated. Sign in at the linked model repositories, review their LTX 2.x Community License terms and access conditions, then obtain only the desired files. The application contains no weights or credentials and never initiates a download. Upstream Comfy nodes may themselves auto-download assets in other workflows; the supplied graphs use explicit model loaders only. This project does not assert that upstream NVIDIA requirements translate to MPS or MLX performance.

For the supplied BF16 single-stage source-video recipe, ComfyUI needs:

| Directory under ComfyUI/models | File |
| --- | --- |
| `diffusion_models` | `ltx-2.5-22b-distilled-transformer-bf16.safetensors` |
| `text_encoders` | `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors` |
| `vae` | `ltx-2.5-video-vae-bf16.safetensors` |
| `loras` | The requested Restore or Refine Details file listed above |

The app does not need an audio VAE, prompt-enhancer model or spatial latent upsampler for these one-stage recipes; the upstream full UI workflow includes additional components for its additional paths. A convolutional video VAE is advertised upstream as another option, but switching it changes the tested configuration and should be retained as a new workflow version. The shipped recipe targets exact filenames and will fail preflight if they are absent. Renaming an incompatible model does not establish compatibility.

Start ComfyUI separately and copy `config.example.toml` to your local config, then set `comfy_url` (default `http://127.0.0.1:8188`) and `comfy_workflow` to the absolute path of `workflows/ltx25-restore.json` or `workflows/ltx25-refine.json`. A configuration selects one operation at a time. Copy a bundle before making installation-specific path changes and retain its `upstream` metadata; graph content is snapshotted and hashed with every job. Run doctor before queueing a render. If your installed node/API schemas differ, use the installed ComfyUI UI to export an API graph and map it in a new bundle; the app rejects plain UI JSON and unmapped/fake capabilities.

Bundle fields are `schema_version`, `operation`, `prompt`, `bindings`, `output_node`, `source_guide_node`, optional `reference_guide_node`/`reference_image_node`, `sampler_node`, and `upstream`. Each binding is `[node_id,input_name]`. Required bindings are `source_video`, `prompt`, `seed`, `width`, `height`, `frame_count`, `fps`; optional supported bindings include `guide_image`, `negative_prompt`, `cfg`, and `output_prefix`. This implementation deliberately checks actual restore/refine node semantics rather than interpreting arbitrary text labels as support.

The adapter uploads prepared video/image bytes using `/upload/image` (the inspected core handler writes uploaded bytes without restricting them to images), submits `/prompt`, polls `/queue` and `/history/{prompt_id}`, and retrieves the configured save node's video through `/view`. Progress is queue/running/history state, not a fabricated sampling percentage. Comfy validation errors and execution exceptions fail the job. It saves the submitted API graph, bundle SHA-256, upstream metadata and prompt ID beside the job artifacts.

Cancellation uses atomic `/api/jobs/{prompt_id}/cancel` in the inspected core. On older servers lacking that route, only the owned pending ID is removed through `/queue`; a running render can continue remotely and the log says so. The app never sends a global `/interrupt`, because older servers may ignore a prompt ID and interrupt someone else's render. Canceled work is never silently adopted as a successful result. Retry starts a new render/version; there is no mid-denoise resume.

Before a new LTX submission, the adapter checks prior prompt IDs recorded by this application's sibling job directories on the same server. Pending or running prior work, or an inability to establish its remote state, blocks another submission with the exact prompt ID. Cancellation confirmation and remote state remain in job provenance, including failure/cancellation paths. This prevents a legacy server's continuing render from silently producing duplicate retries.

The pinned fusion sampler removes appended guide latent frames internally before returning its result; upstream connects it directly to tiled VAE decoding. The app therefore does not add another guide-cropping node. It verifies the retrieved raw video's exact prepared frame count before removing explicitly padded tail frames.

## Ingredients and MLX are separate capabilities

Ingredients `ltx-2.5-22b-ic-lora-ingredients-0.9.safetensors` is documented for reference-sheet-conditioned scene generation. Its composite inventory of characters/props/locations guides a newly generated performance. It is not exposed as restoration of the source film, and is not accepted by the restoration bundle validator.

MLX upstream now documents 2.5 IC-LoRA and Refine Details recipes, so the claim that it only supports text/image-to-video would be stale. However, the inspected `ic_lora.py` image operations are I2V latent-replace/keyframe conditioning; the CLI's negative image indexes are resolved relative to the clip end. They are not the Comfy -1 out-of-clip RoPE actor-reference operation. The current pipeline documentation also flags `stage_2_ic_lora=True` tiled plans as not ported. Its release manifest says 0.17.0 while `PIPELINES.md` still describes current v0.16.3, so documentation alone cannot establish an exact tested recipe.

The app therefore keeps MLX unavailable for restoration/reference rendering until the exact source-video and spatial reference operations are implemented and run on the target hardware. It does not treat int4/int8 model loading, memory capacity, block streaming or I2V support as evidence of full restoration support. M1 Max 32 GB, Mac Studio 36 GB and M5 Max 128 GB can all launch organization, guide preparation and FFmpeg baselines; model speed, memory and fidelity must be measured on the actual machine and recipe.

## Unresolved limitations

- Actual LTX inference, Apple Metal compatibility, model weight integrity and subjective fidelity need a user-installed backend and human review.
- Exact per-node Git versions and model hashes are not exposed by standard `/object_info`; doctor reports discoverable metadata without guessing missing versions.
- The model-card -1 reference examples are documented upstream demonstrations, not proof for this user's film. Native reference size, face placement and motion sensitivity must be evaluated on a short controlled B/C shot.
- Long clips, streaming references, moving subjects, multiple actors and automated tracking need separate implementation and validation. The initial restrictions are explicit in preflight.

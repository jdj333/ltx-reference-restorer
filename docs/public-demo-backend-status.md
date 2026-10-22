# Public demo: LTX backend preflight

Checked **2026-10-21**, including a fresh readiness check during preview polish. These observations are local preflight evidence, not an inference benchmark.

## Observed installation

- The inspected machine was an Apple M1 Max with 32 GB unified memory and a 24-core GPU. macOS reported Metal support; this is not evidence that the selected LTX graph can run on MPS.
- The configured ComfyUI endpoint, `http://127.0.0.1:8188`, refused connections. A second localhost request outside the filesystem/network sandbox also received connection refused.
- Comfy Desktop **1.1.6** was installed. Its local ComfyUI core was **v0.39.2**, commit `3c1b7a17fdf239d35ce98cc777756f572d089795`.
- The inspected installation's custom-node directory contained the example node and websocket image-save node; **ComfyUI-LTXVideo was absent**.
- No `.safetensors`, `.gguf`, `.ckpt`, `.pt`, `.pth`, or `.bin` weight files were found in either the installation's model directory or its configured shared model directory. This inventory covers those configured ComfyUI locations only.
- No active ComfyUI backend process was observed. The existing public-example API and single worker were left running; no additional worker was started for this check.
- No ComfyUI backend was started or stopped, no configuration or installed models were changed, and no weights were downloaded or loaded.

The configured prerequisites are absent. This does not establish whether the recipe would fit memory or complete on any particular hardware after installation. No actual LTX Restore, Refine Details, reference conditioning, MPS or CUDA inference was performed for these public-film examples.

## Prerequisites for a real B/C test

Install a compatible ComfyUI-LTXVideo node package and the model files required by the selected bundled workflow. The current bundles require the following exact filenames:

| Directory under ComfyUI/models | File | Operation |
| --- | --- | --- |
| `diffusion_models` | `ltx-2.5-22b-distilled-transformer-bf16.safetensors` | Both |
| `text_encoders` | `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors` | Both |
| `vae` | `ltx-2.5-video-vae-bf16.safetensors` | Both |
| `loras` | `ltx-2.5-22b-ic-lora-restore-1.0.safetensors` | Restore |
| `loras` | `ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors` | Refine Details |

Model access, terms, upstream source revisions, recipe semantics, and configuration instructions are documented in [integration-notes.md](integration-notes.md). The shipped graphs were reviewed against upstream executable node source; that review and mocked transport tests do not verify model execution. The installed core revision above differs from the graph's inspected upstream revision and still needs runtime schema validation.

After starting the intended ComfyUI instance and configuring `comfy_url` and `comfy_workflow` in a local configuration copied from `config.example.toml`, run:

```sh
RESTORER_CONFIG=/absolute/path/to/local-config.toml uv run restorer doctor
```

Select `workflows/ltx25-restore.json` for the first controlled test. Inspect the reported connectivity, required nodes, advertised model filenames, and workflow blockers. A clean doctor result establishes preflight eligibility only. A real successful job additionally requires submission, actual model processing, output retrieval, and media validation; identity and source-performance fidelity still require human comparison.

For the B/C comparison, use the same public source clip, settings, seed, and workflow: B omits actor-reference conditioning; C uses one approved reference at a fixed placement. Until both real jobs complete, label their results **not run**, and keep conventional FFmpeg baseline results separate from LTX results.

## Preview readiness and next action

The fresh check confirmed the same upstream node/base/Restore repository revisions already recorded in [integration notes](integration-notes.md). The official [Restore model page](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Restore) still requires account access conditions, and official model metadata marks both the Restore and base repositories as gated. No access conditions were accepted during this check. Model access decisions and the intended backend installation must be resolved before loading these files.

The wrapper can be exercised now through its real conventional workflow. The model-specific milestone remains **blocked before submission**. Use the [one-shot pilot procedure](ltx-pilot.md) for exact isolated commands, frozen B/C inputs, technical evidence, runtime/memory recording and a separate human comparison once prerequisites exist. Native Windows is unsupported by the current POSIX worker implementation; Linux CI and the tested macOS baseline do not establish CUDA/MPS inference.

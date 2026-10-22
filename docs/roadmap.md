# Roadmap

1. **Evidence from short shots.** Run the pinned Restore/Refine workflows on actual supported hardware, save memory and runtime measurements, compare baseline/B/C with the same seed and configuration, and conduct human identity/performance review. Broaden codec, VFR, non-square-pixel and interlaced fixture coverage.
2. **Tracking with manual correction.** Add optional face detection and tracking with confidence gaps, editable per-frame landmarks and explicit source/preview/canvas/tile transforms. Preserve the user's chosen reference across a shot.
3. **Moving and multiple actors.** Enable only with verified backend reference placement semantics, per-actor masks, crossing/occlusion handling and tests that prevent reference mixing. Preserve fixed manual setup as a fallback.
4. **Longer clips.** Add deliberate shot/chunk boundaries, overlap/trim manifests, disk/memory budgeting and temporal review. Do not label independently rendered chunks a seamless performance or promise unsupported mid-render resume.
5. **Additional backends.** Reassess native MLX when stage-two restoration adapters and spatial reference placement are implemented and tested. Keep generation, Ingredients, lip dubbing and retakes separate from performance-preserving restoration.
6. **Review improvements.** Broader browser motion/audio synchronization coverage alongside exact decoded paused stills, richer face crops and note export, optional imperfect similarity indicators and project archive verification. Human approval stays explicit and attached to immutable output hashes.

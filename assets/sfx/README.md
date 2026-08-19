# Built-in sound effects

This directory contains Alexandria's sound-effect catalog for cultivation novels. The
original starter WAV files are generated locally by `scripts/generate_builtin_sfx.py` from
deterministic procedural synthesis and therefore do not depend on third-party recordings.
The `recorded/` subtree contains user-provided recordings with separate provenance notes.

Run the generator again after cloning if the WAV files are missing:

    python3 scripts/generate_builtin_sfx.py

Each cue may have a primary `file` plus recorded `variants`. Rendering chooses a variant
deterministically from the line and cue, so reruns remain reproducible. You can replace any
WAV with a higher-quality recording while keeping the filename and cue in `manifest.json`.
New cues must be added to the manifest before the chapter analyzer will use them. Keep speech
clarity in mind: ambience defaults are intentionally much quieter than one-shot combat effects.

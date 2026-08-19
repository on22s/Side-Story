# Alexandria Audiobook Generator

English | [中文](README_CN.md)

Alexandria is a file-based CLI pipeline for turning books into fully voiced audiobooks. The supported workflow analyzes chapters with Codex CLI, assigns persistent character voices, generates TTS audio, and publishes chapter M4B files.

The legacy Alexandria browser UI and its HTTP API have been removed. There is no local web server in the supported pipeline. Audiobookshelf remains a separate optional service for library management and playback.

## Architecture

- cli.py owns book projects, chapter mapping, analysis state, character IDs, voice IDs, caching, resume, and M4B export.
- app/tts.py is the shared TTS backend. It supports the local Qwen3-TTS engine and external HTTP/Gradio TTS endpoints.
- assets/sfx/ contains the built-in cultivation-novel SFX catalog. Chapter analysis emits controlled cues and FFmpeg mixes them on the dialogue timeline.
- books/<book>/output/chapters/ is the publish directory watched by Audiobookshelf.
- Codex CLI is invoked as an ephemeral read-only subprocess for chapter analysis and summaries.

## Requirements

- Python with the project dependencies installed
- Codex CLI installed and authenticated with codex auth login
- ffmpeg available on PATH
- A local Qwen3-TTS installation or the configured external TTS endpoints
- GPU is recommended for local TTS; external TTS can be used without a local GPU

The default CLI analysis configuration is gpt-5.6-luna with max reasoning. Override it with ALEXANDRIA_CODEX_MODEL or ALEXANDRIA_CODEX_REASONING_EFFORT when needed.

## Quick start

Initialize a book project:

    python cli.py init --book fanren --input /data/books/fanren.epub --title "凡人修仙传"

Plan and generate a range of novel chapters:

    python generate_chapters.py 742 10 --plan
    python generate_chapters.py 742 10 --continue

The range uses the novel original chapter numbers. The count includes the starting chapter.

Inspect status or resume after an interruption:

    python cli.py status --book fanren
    python cli.py run --book fanren --continue

Export a combined M4B when needed:

    python cli.py export --book fanren --format m4b

For a safe preflight without Codex or TTS:

    python cli.py run --book fanren --from 742 --count 1 --dry-run

## Sound effects

Sound effects are enabled by default. The catalog contains 21 deterministic, locally generated WAV assets plus 28 user-provided recorded variants for weapon clashes, qi and spell effects, thunder, explosions, movement, creatures, bells, and common ambience. Variant selection is deterministic for reproducible rerenders. Regenerate the built-in subset with:

    python3 scripts/generate_builtin_sfx.py

New chapter analyses write controlled cues into each script line's `effects` array. Re-analyze an existing chapter with `--force` to add automatic cues, then render it normally. `assets/sfx/manifest.json` is the catalog and mixing defaults. Rendered chapters retain `dialogue.wav` as the speech-only master and write resolved cue timestamps to `sfx_timeline.json`.

Disable mixing for a run with `ALEXANDRIA_SFX_ENABLED=0`. Higher-quality WAV files can replace the built-ins without code changes as long as their manifest cue and filename remain stable.

## Book layout

    books/<book>/
    ├── book.json
    ├── state/
    │   ├── characters.json
    │   ├── aliases.json
    │   ├── voices.json
    │   └── novel_chapters.json
    ├── chapters/000001/
    │   ├── source.txt
    │   ├── script.json
    │   ├── summary.txt
    │   ├── status.json
    │   ├── dialogue.wav
    │   ├── sfx_timeline.json
    │   └── audio.m4b
    └── output/chapters/

Analysis and TTS state are checkpointed per chapter. If TTS fails, the next run can reuse the existing analysis and continue from the audio stage.

## Audiobookshelf

Audiobookshelf is not part of the CLI process. The included Compose file only manages the Audiobookshelf service:

    docker compose up -d audiobookshelf

It listens on http://localhost:13378, stores its configuration under data/audiobookshelf/, and reads the project books through the read-only mount ./books:/audiobooks:ro. Enable the Audiobookshelf File Watcher for automatic discovery of newly published chapters.

## License

MIT

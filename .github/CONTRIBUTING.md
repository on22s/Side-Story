# Contributing to Alexandria

Thanks for your interest in contributing! Here are a few guidelines to help PRs get reviewed and merged smoothly.

## Branch Workflow

- **`main`** is the stable release branch. Users install from `main`.
- **`dev`** is the integration branch where new features land first.

**All pull requests must target the `dev` branch, not `main`.** PRs targeting `main` will be asked to retarget.

## PR Guidelines

### Keep PRs focused
Each PR should address **one feature or fix**. Small, focused PRs are easier to review, less likely to introduce regressions, and get merged faster. If you have multiple ideas, open multiple PRs.

### Don't include personal tooling
- No CI/CD configs for tools the project doesn't use (Gemini workflows, etc.)
- No AI assistant config files (`.claude/skills/`, `.cursor/`, etc.)
- No shell scripts with hardcoded local paths
- Add these to your fork's `.gitignore` instead

### Don't replace existing files wholesale
- Don't rewrite `README.md`, `requirements.txt`, or other core files — modify them incrementally
- If a feature needs documentation, add it alongside existing docs

### Preserve cross-platform compatibility
Alexandria runs on Linux, Windows, and macOS. Avoid platform-specific APIs without fallbacks (e.g., `select.select()` on pipes doesn't work on Windows).

### Preserve existing functionality
- Don't add top-level imports that break startup on systems without optional dependencies (e.g., `import torch` in `app.py`)
- Don't remove existing tests — update them if behavior changes
- Don't remove existing imports unless you've verified no code path uses them

## Project Structure

Keep shared runtime code in `app/`. The supported long-form workflow is the
file-based CLI in `cli.py`; `app/tts.py` is the shared TTS backend.

```
app/           # Shared TTS and voice utilities
builtin_lora/  # Pre-trained LoRA presets
books/         # Book projects and generated audio (local workspace)
```

## Testing

Before submitting a PR, run the CLI checks relevant to the change:

```bash
python cli.py status --book fanren
python generate_chapters.py 1 1 --plan
```

## Getting Started

1. Fork the repo and create a feature branch from `dev`
2. Make your changes
3. Run the relevant CLI checks and verify they pass
4. Test manually with a dry-run or a small chapter range
5. Open a PR targeting `dev`

# Agent workflow

## Chapter generation

- Run chapter work with the project virtual environment. The Codex runner resolves `codex` to an absolute executable path, including `~/.local/bin/codex`, so background jobs must not depend on an interactive shell PATH.
- Exact source-text coverage validation is disabled by default. Do not enable it for normal audiobook generation; small omissions, insertions, or rewrites are acceptable. `ALEXANDRIA_COVERAGE_MODE=warn|strict` is diagnostic-only.
- Codex supports parallel analysis; do not impose a fixed two-worker limit. Eight lightweight concurrent CLI requests are verified on this host. Use disjoint chapter ranges, make worker count configurable, and avoid duplicate work on the same chapter.
- Do not launch generation through a transient user systemd unit without passing the current PATH and proxy environment. The user systemd manager previously retained dead `127.0.0.1:7890` proxy variables while the live sing-box ports were different. The pipeline now fails fast when a configured loopback proxy is not listening.
- Finished per-chapter M4B sources belong in `books/<book>/output/chapter_sources/` and must be retained.

## Rolling merged edition

- After a generation batch, run `.venv/bin/python scripts/update_serial.py`.
- The only retained merged audio is `books/fanren/output/chapters/fanren_serial.m4b`. Do not create or retain merged-edition backups or range exports; they are reproducible from `chapter_sources/`.
- The command is complete only when its Audiobookshelf API verification reports the expected chapter count and final title. Do not rely on the file watcher or a full library scan.
- SQLite safety backups made immediately before a targeted Audiobookshelf catalog update are not audio editions and should be retained for database recovery.

## Sandbox escalation policy

When a command fails because of the Codex sandbox and subsequently succeeds
after auto-review/escalation:

- If the command is a routine, repeatable, non-destructive operation required
  for this repository, consider adding a narrow allow rule to
  `.codex/rules/default.rules`.
- Prefer the narrowest useful command prefix.
- Never allow generic shell interpreters such as `bash -lc`, `sh -c`, or
  unrestricted `python`.
- Never automatically allow destructive commands such as `rm`, `sudo`,
  `git reset --hard`, `git clean`, or force pushes.
- If the repeated escalation is caused by network access or a fixed external
  writable directory, prefer fixing the sandbox configuration rather than
  adding an execution rule.
- Validate newly added rules with `codex execpolicy check`.

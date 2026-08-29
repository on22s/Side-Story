#!/usr/bin/env python3
"""并行预分析并流水线渲染一段小说章节。

分析阶段按章分发到可配置数量的独立 Codex 子进程，并通过
ALEXANDRIA_DEFER_ANALYSIS_STATE=1 避免并发写共享人物/声音状态。
任一章节分析完成后，协调器立即以单个串行渲染进程完成摘要、人物状态
收敛和 TTS；因此分析与 TTS 可以重叠，同时不会并发写同一章或共享状态。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Set, TextIO

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


def _preflight(root: Path) -> None:
    checks = [
        ([sys.executable, "-m", "py_compile", str(root / "cli.py")], "cli.py"),
        (["bash", "-n", str(root / "start_xc_tts_tunnel.sh")], "start_xc_tts_tunnel.sh"),
    ]
    for command, label in checks:
        result = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"preflight failed for {label}: {detail}")


@dataclass
class AnalysisJob:
    novel: int
    attempt: int
    process: subprocess.Popen
    log_handle: TextIO
    log_path: Path


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="并行分析章节，并在分析完成后流水线渲染 TTS"
    )
    parser.add_argument("start", type=int, help="起始小说章节号")
    parser.add_argument("count", type=int, help="连续章节数")
    parser.add_argument("--book", default="fanren")
    parser.add_argument("--arc", default="main")
    parser.add_argument("--books-dir")
    parser.add_argument(
        "--workers",
        type=int,
        default=_int_env("ALEXANDRIA_ANALYSIS_WORKERS", 8),
        help="并发分析进程数，默认 8，也可用 ALEXANDRIA_ANALYSIS_WORKERS",
    )
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--continue", dest="continue_", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--analysis-retries",
        type=int,
        default=_int_env("ALEXANDRIA_ANALYSIS_RETRIES", 1, 0),
    )
    parser.add_argument(
        "--render-retries",
        type=int,
        default=_int_env("ALEXANDRIA_RENDER_RETRIES", 1, 0),
    )
    parser.add_argument("--log-dir", help="批次日志目录，默认写入 output/generation_logs")
    return parser


def _codex_env(base: Dict[str, str], defer_state: bool) -> Dict[str, str]:
    env = dict(base)
    if defer_state:
        env["ALEXANDRIA_DEFER_ANALYSIS_STATE"] = "1"
    else:
        env.pop("ALEXANDRIA_DEFER_ANALYSIS_STATE", None)
    configured = env.get("ALEXANDRIA_CODEX_BIN")
    resolved = configured or shutil.which("codex")
    if not resolved:
        candidate = Path.home() / ".local" / "bin" / "codex"
        if candidate.is_file():
            resolved = str(candidate)
    if resolved:
        env["ALEXANDRIA_CODEX_BIN"] = resolved
    return env


def _status(pipeline: cli.BookPipeline, novel: int, arc: str) -> tuple[dict, Path]:
    internal = pipeline.internal_chapter(novel, arc)
    status = cli.load_chapter_status(pipeline.book_dir, internal)
    return status, cli.chapter_root(pipeline.book_dir, internal)


def _analysis_ready(pipeline: cli.BookPipeline, novel: int, arc: str) -> bool:
    internal = pipeline.internal_chapter(novel, arc)
    chapter_dir = cli.chapter_root(pipeline.book_dir, internal)
    status = cli.load_chapter_status(pipeline.book_dir, internal)
    return bool(status.get("analysis")) and (chapter_dir / "script.json").is_file()


def _audio_done(pipeline: cli.BookPipeline, novel: int, arc: str) -> bool:
    internal = pipeline.internal_chapter(novel, arc)
    chapter_dir = cli.chapter_root(pipeline.book_dir, internal)
    status = cli.load_chapter_status(pipeline.book_dir, internal)
    return bool(status.get("done")) and (
        (chapter_dir / "audio.m4b").is_file()
        or (chapter_dir / "audio.m4a").is_file()
    )


def _command_prefix(root: Path, args: argparse.Namespace) -> List[str]:
    command = [sys.executable, str(root / "cli.py")]
    command.extend(["--books-dir", args.books_dir] if args.books_dir else [])
    return command


def _analysis_command(root: Path, args: argparse.Namespace, novel: int) -> List[str]:
    command = _command_prefix(root, args)
    command.extend([
        "analyze",
        "--book", args.book,
        "--arc", args.arc,
        "--chapter", str(novel),
    ])
    if args.force:
        command.append("--force")
    return command


def _render_command(root: Path, args: argparse.Namespace, novel: int) -> List[str]:
    command = _command_prefix(root, args)
    command.extend([
        "run",
        "--book", args.book,
        "--arc", args.arc,
        "--chapter", str(novel),
    ])
    return command


def _log_directory(book_dir: Path, requested: Optional[str]) -> Path:
    if requested:
        directory = Path(requested).expanduser()
        if not directory.is_absolute():
            directory = book_dir / directory
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        directory = book_dir / "output" / "generation_logs" / f"parallel_{stamp}_{os.getpid()}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _print_render_line(novel: int, line: str) -> None:
    stripped = line.strip()
    if not stripped:
        return
    interesting = (
        "codex model:",
        "rendering ",
        "rendered line",
        "VoiceDesign",
        "TTS:",
        "DONE",
        "failed",
        "error:",
        "warning:",
    )
    if stripped.startswith(interesting) or "DONE" in stripped:
        print(f"[render {novel}] {stripped}", flush=True)


def _render_one(
    root: Path,
    args: argparse.Namespace,
    novel: int,
    log_dir: Path,
    env: Dict[str, str],
) -> bool:
    for attempt in range(1, args.render_retries + 2):
        log_path = log_dir / f"render_{novel:04d}_attempt{attempt}.log"
        print(
            f"[render {novel}] start attempt={attempt} log={log_path}",
            flush=True,
        )
        command = _render_command(root, args, novel)
        with log_path.open("w", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                log_handle.write(line)
                log_handle.flush()
                _print_render_line(novel, line)
            code = process.wait()
        if code == 0:
            print(f"[render {novel}] complete attempt={attempt}", flush=True)
            return True
        print(f"[render {novel}] failed exit={code}", flush=True)
        if attempt <= args.render_retries:
            print(f"[render {novel}] retrying from saved checkpoints", flush=True)
    return False


def _launch_analysis(
    root: Path,
    args: argparse.Namespace,
    novel: int,
    attempt: int,
    log_dir: Path,
    env: Dict[str, str],
) -> AnalysisJob:
    log_path = log_dir / f"analyze_{novel:04d}_attempt{attempt}.log"
    log_handle = log_path.open("w", encoding="utf-8")
    command = _analysis_command(root, args, novel)
    process = subprocess.Popen(
        command,
        cwd=str(root),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(
        f"[analyze {novel}] start attempt={attempt} pid={process.pid} "
        f"log={log_path}",
        flush=True,
    )
    return AnalysisJob(novel, attempt, process, log_handle, log_path)


def _close_job(job: AnalysisJob) -> None:
    try:
        job.log_handle.close()
    except OSError:
        pass


def _terminate_jobs(jobs: Iterable[AnalysisJob]) -> None:
    for job in jobs:
        if job.process.poll() is None:
            job.process.terminate()
    deadline = time.monotonic() + 10
    for job in jobs:
        if job.process.poll() is None:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                job.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                job.process.kill()
        _close_job(job)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _preflight(ROOT_DIR)
        global cli
        import cli
    except Exception as exc:
        print(f"startup preflight failed: {exc}", file=sys.stderr)
        return 2
    if args.start <= 0 or args.count <= 0:
        raise SystemExit("start/count 必须是正整数")
    if args.workers <= 0:
        raise SystemExit("--workers 必须是正整数")
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds 必须是正数")

    root = Path(__file__).resolve().parents[1]
    books_dir = cli.resolve_books_dir(args.books_dir)
    book_dir = cli.book_root(books_dir, args.book)
    pipeline = cli.BookPipeline(book_dir)
    selected_internal = cli.select_chapters(
        pipeline.book,
        first=args.start,
        count=args.count,
        continue_=args.continue_ and not args.force,
        book_dir=book_dir,
        arc=args.arc,
    )
    if not selected_internal:
        print("范围内章节已经全部完成")
        return 0
    novels = [pipeline.novel_chapter_number(number) for number in selected_internal]
    log_dir = _log_directory(book_dir, args.log_dir)
    started_at = time.monotonic()
    print(
        f"batch start chapters={novels[0]}-{novels[-1]} count={len(novels)} "
        f"workers={min(args.workers, len(novels))} log_dir={log_dir}",
        flush=True,
    )

    base_env = os.environ.copy()
    analysis_env = _codex_env(base_env, defer_state=True)
    render_env = _codex_env(base_env, defer_state=False)
    pending_analysis: Deque[int] = deque()
    render_targets: List[int] = []
    rendered: Set[int] = set()
    render_failed: Set[int] = set()
    analysis_failed: Set[int] = set()
    attempts: Dict[int, int] = {}

    for novel in novels:
        status, chapter_dir = _status(pipeline, novel, args.arc)
        needs_analysis = args.force or not status.get("analysis") or not (
            chapter_dir / "script.json"
        ).is_file()
        if needs_analysis:
            pending_analysis.append(novel)
        if not _audio_done(pipeline, novel, args.arc):
            render_targets.append(novel)
        else:
            rendered.add(novel)

    active: Dict[int, AnalysisJob] = {}
    last_heartbeat = 0.0
    try:
        while pending_analysis or active or (
            set(render_targets) - rendered - render_failed
        ):
            while pending_analysis and len(active) < min(args.workers, len(novels)):
                novel = pending_analysis.popleft()
                attempts[novel] = attempts.get(novel, 0) + 1
                active[novel] = _launch_analysis(
                    root, args, novel, attempts[novel], log_dir, analysis_env
                )

            for novel, job in list(active.items()):
                code = job.process.poll()
                if code is None:
                    continue
                _close_job(job)
                del active[novel]
                if code == 0:
                    print(
                        f"[analyze {novel}] complete attempt={job.attempt}",
                        flush=True,
                    )
                elif job.attempt <= args.analysis_retries:
                    print(
                        f"[analyze {novel}] failed exit={code}; retrying "
                        "from saved checkpoints",
                        flush=True,
                    )
                    pending_analysis.append(novel)
                else:
                    analysis_failed.add(novel)
                    print(
                        f"[analyze {novel}] failed permanently exit={code}; "
                        f"see {job.log_path}",
                        flush=True,
                    )

            ready = [
                novel
                for novel in render_targets
                if novel not in rendered
                and novel not in render_failed
                and novel not in analysis_failed
                and _analysis_ready(pipeline, novel, args.arc)
            ]
            if ready:
                novel = ready[0]
                if _render_one(root, args, novel, log_dir, render_env):
                    rendered.add(novel)
                else:
                    render_failed.add(novel)
                continue

            if not pending_analysis and not active:
                missing = [
                    novel for novel in render_targets
                    if novel not in rendered and novel not in render_failed
                ]
                if missing:
                    analysis_failed.update(missing)
                    print(
                        f"analysis finished but no renderable script was checkpointed: {missing}",
                        flush=True,
                    )
                break

            now = time.monotonic()
            if now - last_heartbeat >= 30:
                waiting = [
                    novel for novel in render_targets
                    if novel not in rendered and novel not in render_failed
                ]
                print(
                    f"heartbeat elapsed={now - started_at:.0f}s "
                    f"analysis_active={len(active)} analysis_waiting={len(pending_analysis)} "
                    f"rendered={len(rendered)}/{len(render_targets)} "
                    f"render_waiting={waiting}",
                    flush=True,
                )
                last_heartbeat = now
            time.sleep(args.poll_seconds)

    except KeyboardInterrupt:
        print("interrupted; terminating analysis workers", flush=True)
        _terminate_jobs(active.values())
        return 130
    finally:
        _terminate_jobs(active.values())

    unresolved = [
        novel for novel in render_targets
        if novel not in rendered and novel not in render_failed
    ]
    elapsed = time.monotonic() - started_at
    print(
        f"batch end elapsed={elapsed:.1f}s rendered={len(rendered)}/{len(render_targets)} "
        f"analysis_failed={sorted(analysis_failed)} render_failed={sorted(render_failed)} "
        f"unresolved={unresolved}",
        flush=True,
    )
    return 1 if analysis_failed or render_failed or unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a rolling M4B edition and synchronize it with Audiobookshelf."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import cli  # noqa: E402


class SerialUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProbeResult:
    chapters: list[dict[str, Any]]
    duration: float


@dataclass(frozen=True)
class AbsItem:
    item_id: str
    library_id: str
    media_id: str
    path: str
    token: str


def parse_probe_data(data: dict[str, Any]) -> ProbeResult:
    chapters: list[dict[str, Any]] = []
    for index, raw in enumerate(data.get("chapters") or []):
        try:
            start = float(raw["start_time"])
            end = float(raw["end_time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SerialUpdateError(f"第 {index + 1} 个章节缺少有效时间范围") from exc
        title = str((raw.get("tags") or {}).get("title") or f"Chapter {index + 1}")
        try:
            chapter_id = int(raw.get("id", index))
        except (TypeError, ValueError):
            chapter_id = index
        if end <= start:
            raise SerialUpdateError(f"章节时间范围无效：{title}")
        chapters.append({"start": start, "end": end, "title": title, "id": chapter_id})
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError) as exc:
        raise SerialUpdateError("M4B 总时长无效") from exc
    if not chapters or duration <= 0:
        raise SerialUpdateError("M4B 没有有效章节或总时长")
    return ProbeResult(chapters=chapters, duration=duration)


def probe_m4b(path: Path) -> ProbeResult:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SerialUpdateError("缺少 ffprobe，请先安装 ffmpeg")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_chapters", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SerialUpdateError(f"ffprobe 读取失败：{result.stderr.strip()[-600:]}")
    try:
        return parse_probe_data(json.loads(result.stdout))
    except json.JSONDecodeError as exc:
        raise SerialUpdateError("ffprobe 返回了无效 JSON") from exc


def published_source(pipeline: cli.BookPipeline, novel_number: int, arc: str) -> Path:
    internal = pipeline.chapter_maps[arc][novel_number]
    name = cli.chapter_audio_filename(
        pipeline.book_dir, pipeline.book, internal, arc=arc, novel_number=novel_number
    )
    return pipeline.book_dir / "output" / cli.CHAPTER_SOURCE_OUTPUT_DIRNAME / name


def discover_last_ready(pipeline: cli.BookPipeline, first: int, arc: str) -> tuple[int, list[Path]]:
    mapping = pipeline.chapter_maps.get(arc) or {}
    if first not in mapping:
        raise SerialUpdateError(f"起始章节 {first} 不在正文映射中")
    sources: list[Path] = []
    current = first
    while current in mapping:
        source = published_source(pipeline, current, arc)
        if not source.exists() or source.stat().st_size == 0:
            break
        sources.append(source)
        current += 1
    if not sources:
        raise SerialUpdateError(f"从第 {first} 章起没有连续可用的单章音频")
    return current - 1, sources


def selected_sources(pipeline: cli.BookPipeline, first: int, last: int, arc: str) -> list[Path]:
    mapping = pipeline.chapter_maps.get(arc) or {}
    paths: list[Path] = []
    for number in range(first, last + 1):
        if number not in mapping:
            raise SerialUpdateError(f"第 {number} 章不在正文映射中")
        path = published_source(pipeline, number, arc)
        if not path.exists() or path.stat().st_size == 0:
            raise SerialUpdateError(f"第 {number} 章缺少已发布的单章音频：{path.name}")
        paths.append(path)
    return paths


def edition_is_current(destination: Path, expected_count: int, sources: Sequence[Path]) -> bool:
    if not destination.exists() or destination.stat().st_size == 0:
        return False
    try:
        probe = probe_m4b(destination)
    except SerialUpdateError:
        return False
    newest_source = max(path.stat().st_mtime_ns for path in sources)
    return len(probe.chapters) == expected_count and destination.stat().st_mtime_ns >= newest_source


def atomic_publish(generated: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as target, generated.open("rb") as source:
            shutil.copyfileobj(source, target, length=4 * 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def abs_host_path(container_path: str) -> Path:
    """Map an Audiobookshelf container path back to this compose checkout."""
    container_root = PurePosixPath(
        os.environ.get("AUDIOBOOKSHELF_CONTAINER_ROOT", "/audiobooks")
    )
    path = PurePosixPath(container_path)
    try:
        relative = path.relative_to(container_root)
    except ValueError as exc:
        raise SerialUpdateError(
            f"Audiobookshelf 文件路径不在挂载根目录下：{container_path}"
        ) from exc

    host_root = Path(
        os.environ.get("AUDIOBOOKSHELF_HOST_ROOT", str(ROOT / "books"))
    ).expanduser().resolve()
    target = (host_root / Path(*relative.parts)).resolve()
    try:
        target.relative_to(host_root)
    except ValueError as exc:
        raise SerialUpdateError(
            f"Audiobookshelf 文件路径解析后越过宿主机挂载根目录：{target}"
        ) from exc
    return target


def publish_to_abs_path(serial: Path, item: AbsItem) -> Path:
    """Keep the file at the path Audiobookshelf actually indexes in sync.

    A book may have been generated under its own project directory while the
    existing Audiobookshelf library indexes a shared mounted directory. In
    that case, publish an atomic copy to the indexed host path before asking
    Audiobookshelf to refresh its metadata.
    """
    target = abs_host_path(item.path)
    if target.resolve() != serial.resolve():
        atomic_publish(serial, target)
        print(f"Audiobookshelf 文件已同步：{target}")
    return target


def connect_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def find_abs_item(db_path: Path, destination_name: str) -> AbsItem:
    with connect_db(db_path) as connection:
        row = connection.execute(
            """SELECT li.id AS item_id, li.libraryId AS library_id,
                      li.mediaId AS media_id, li.path AS path
               FROM libraryItems li
               WHERE li.isFile = 1 AND li.path LIKE ?
               ORDER BY li.updatedAt DESC LIMIT 1""",
            (f"%/output/chapters/{destination_name}",),
        ).fetchone()
        user = connection.execute(
            "SELECT token FROM users WHERE type = 'root' AND isActive = 1 LIMIT 1"
        ).fetchone()
    if row is None:
        raise SerialUpdateError(f"Audiobookshelf 中找不到固定合并版：{destination_name}")
    if user is None or not user["token"]:
        raise SerialUpdateError("Audiobookshelf 中没有可用的 root API token")
    return AbsItem(row["item_id"], row["library_id"], row["media_id"], row["path"], user["token"])


def api_json(
    server: str,
    token: str,
    path: str,
    method: str = "GET",
    expect_json: bool = True,
) -> dict[str, Any]:
    request = Request(
        f"{server.rstrip('/')}{path}", data=b"" if method == "POST" else None,
        method=method, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SerialUpdateError(f"Audiobookshelf API 请求失败：{method} {path}: {exc}") from exc
    if not payload or not expect_json:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SerialUpdateError(f"Audiobookshelf API 返回了无效 JSON：{path}") from exc


def api_chapters(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return (payload.get("media") or {}).get("chapters") or []


def chapters_match(actual: Sequence[dict[str, Any]], expected: Sequence[dict[str, Any]]) -> bool:
    return bool(expected) and len(actual) == len(expected) and str(actual[-1].get("title")) == str(expected[-1].get("title"))


def docker_status(container: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", container, "--format", "{{.State.Status}}"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SerialUpdateError(f"找不到 Audiobookshelf 容器 {container!r}")
    return result.stdout.strip()


def docker_action(action: str, container: str) -> None:
    result = subprocess.run(["docker", action, container], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SerialUpdateError(f"docker {action} {container} 失败：{result.stderr.strip()[-500:]}")


def sqlite_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " +00:00"


def patch_abs_database(db_path: Path, item: AbsItem, probe: ProbeResult, serial: Path, container: str) -> Path:
    was_running = docker_status(container) == "running"
    if was_running:
        docker_action("stop", container)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = db_path.with_name(f"{db_path.stem}.before_serial_sync_{stamp}{db_path.suffix}")
    try:
        shutil.copy2(db_path, backup)
        size = serial.stat().st_size
        mtime_ms = int(serial.stat().st_mtime * 1000)
        timestamp = sqlite_timestamp()
        with connect_db(db_path) as connection:
            row = connection.execute("SELECT audioFiles FROM books WHERE id = ?", (item.media_id,)).fetchone()
            if row is None:
                raise SerialUpdateError("Audiobookshelf 书籍记录已不存在")
            try:
                audio_files = json.loads(row["audioFiles"] or "[]")
            except json.JSONDecodeError:
                audio_files = []
            if audio_files:
                audio_files[0]["chapters"] = probe.chapters
                audio_files[0]["duration"] = probe.duration
                metadata = audio_files[0].setdefault("metadata", {})
                metadata["size"] = size
                metadata["mtimeMs"] = mtime_ms
            connection.execute(
                "UPDATE books SET chapters = ?, audioFiles = ?, duration = ?, updatedAt = ? WHERE id = ?",
                (json.dumps(probe.chapters, ensure_ascii=False, separators=(",", ":")),
                 json.dumps(audio_files, ensure_ascii=False, separators=(",", ":")),
                 probe.duration, timestamp, item.media_id),
            )
            connection.execute(
                "UPDATE libraryItems SET size = ?, mtime = ?, updatedAt = ? WHERE id = ?",
                (size, timestamp, timestamp, item.item_id),
            )
    finally:
        if was_running:
            docker_action("start", container)
    return backup


def wait_for_api(server: str, item: AbsItem, expected: ProbeResult, timeout: int = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            payload = api_json(server, item.token, f"/api/items/{quote(item.item_id)}?expanded=1")
            if chapters_match(api_chapters(payload), expected.chapters):
                return payload
        except SerialUpdateError as exc:
            last_error = exc
        time.sleep(2)
    detail = f"；最后错误：{last_error}" if last_error else ""
    raise SerialUpdateError(f"Audiobookshelf API 在 {timeout} 秒内未显示最新章节{detail}")


def synchronize_abs(args: argparse.Namespace, serial: Path, probe: ProbeResult) -> Path | None:
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = (ROOT / db_path).resolve()
    if not db_path.exists():
        raise SerialUpdateError(f"Audiobookshelf 数据库不存在：{db_path}")
    item = find_abs_item(db_path, serial.name)
    publish_to_abs_path(serial, item)
    payload = api_json(args.server, item.token, f"/api/items/{quote(item.item_id)}?expanded=1")
    if chapters_match(api_chapters(payload), probe.chapters):
        return None
    backup = patch_abs_database(db_path, item, probe, serial, args.container)
    wait_for_api(args.server, item, probe)
    time.sleep(3)
    stable = api_json(args.server, item.token, f"/api/items/{quote(item.item_id)}?expanded=1")
    if not chapters_match(api_chapters(stable), probe.chapters):
        raise SerialUpdateError("Audiobookshelf 延迟复核失败，章节在服务启动后再次回退")
    return backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一键更新固定文件名合并版并同步 Audiobookshelf")
    parser.add_argument("--book", default="fanren", help="书籍 ID（默认 fanren）")
    parser.add_argument("--from-chapter", type=int, default=757, help="合并版起始章（默认 757）")
    parser.add_argument("--to-chapter", type=int, help="末章；默认自动发现连续生成的最新章")
    parser.add_argument("--arc", default="main", help="章节分区（默认 main）")
    parser.add_argument("--force", action="store_true", help="即使产物已是最新也重新编码")
    parser.add_argument("--dry-run", action="store_true", help="只展示范围和计划，不写文件或服务")
    parser.add_argument("--skip-audiobookshelf", action="store_true", help="只更新本地合并版")
    parser.add_argument("--container", default="audiobookshelf", help="Audiobookshelf 容器名")
    parser.add_argument("--server", default="http://127.0.0.1:13378", help="Audiobookshelf 地址")
    parser.add_argument("--db", default="data/audiobookshelf/config/absdatabase.sqlite", help="Audiobookshelf SQLite 路径")
    return parser


def run(args: argparse.Namespace) -> int:
    book_dir = ROOT / "books" / args.book
    if not book_dir.exists():
        raise SerialUpdateError(f"书籍项目不存在：{book_dir}")
    pipeline = cli.BookPipeline(book_dir)
    arc = cli.normalize_arc(args.arc)
    first = args.from_chapter
    if args.to_chapter is None:
        last, sources = discover_last_ready(pipeline, first, arc)
    else:
        last = args.to_chapter
        if last < first:
            raise SerialUpdateError("末章不能小于起始章")
        sources = selected_sources(pipeline, first, last, arc)
    expected_count = last - first + 1
    destination = book_dir / "output" / "chapters" / f"{args.book}_serial.m4b"
    current = edition_is_current(destination, expected_count, sources)
    print(f"合并范围：{first}-{last}（{expected_count} 章）")
    print(f"固定产物：{destination}")
    if args.dry_run:
        print(f"计划：{'跳过重新编码' if current and not args.force else '重新导出并原子发布'}")
        print(f"Audiobookshelf：{'跳过' if args.skip_audiobookshelf else '校验 API，不一致时备份并精准同步'}")
        return 0
    if current and not args.force:
        print("合并版已是最新，跳过重新编码。")
    else:
        generated = pipeline.export_m4b(first, last, arc=arc)
        generated_probe = probe_m4b(generated)
        if len(generated_probe.chapters) != expected_count:
            raise SerialUpdateError(f"导出章节数不符：期望 {expected_count}，实际 {len(generated_probe.chapters)}")
        atomic_publish(generated, destination)
        if generated != destination:
            generated.unlink(missing_ok=True)
        print("合并版已原子更新。")
    final_probe = probe_m4b(destination)
    if len(final_probe.chapters) != expected_count:
        raise SerialUpdateError(f"固定合并版章节数不符：期望 {expected_count}，实际 {len(final_probe.chapters)}")
    if args.skip_audiobookshelf:
        print(f"完成：本地合并版共 {len(final_probe.chapters)} 章，末章 {final_probe.chapters[-1]['title']}。")
        return 0
    db_backup = synchronize_abs(args, destination, final_probe)
    if db_backup:
        print(f"Audiobookshelf 数据库备份：{db_backup}")
    print(f"完成：本地与 Audiobookshelf API 均为 {len(final_probe.chapters)} 章，末章 {final_probe.chapters[-1]['title']}。")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (SerialUpdateError, cli.PipelineError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

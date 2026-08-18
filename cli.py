#!/usr/bin/env python3
"""Alexandria long-form audiobook CLI.

The CLI is intentionally small and file based.  A book is a directory under
``books/``; Python owns all state transitions and Codex is only asked to
understand the current chapter.  The existing ``app/tts.py`` module remains
the audio backend.

Typical usage::

    python cli.py init --book fanren --input /data/books/fanren.txt
    python cli.py run --book fanren --from 1
    python cli.py run --book fanren --continue
    python cli.py status --book fanren
    python cli.py export --book fanren --format m4b

No HTTP server, database, vector index, or long-lived Codex session is used.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import wave
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote
import xml.etree.ElementTree as ET


ROOT_DIR = Path(__file__).resolve().parent
APP_DIR = ROOT_DIR / "app"
DEFAULT_BOOKS_DIR = ROOT_DIR / "books"
SCHEMA_VERSION = 1
PROMPT_VERSION = os.environ.get("ALEXANDRIA_PROMPT_VERSION", "script_v2_roles_profiles")
SUMMARY_PROMPT_VERSION = os.environ.get("ALEXANDRIA_SUMMARY_PROMPT_VERSION", "summary_v1")
CODEX_TIMEOUT_SECONDS = int(os.environ.get("ALEXANDRIA_CODEX_TIMEOUT", "1800"))
DEFAULT_CODEX_MODEL = "gpt-5.3-codex-spark"
CHAPTER_AUDIO_SUFFIX = ".m4b"
LEGACY_CHAPTER_AUDIO_SUFFIX = ".m4a"


class PipelineError(RuntimeError):
    """An expected, user-facing pipeline error."""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically so an interrupted chapter cannot corrupt state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"无法读取 JSON 文件 {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def validate_book_id(book: str) -> str:
    book = str(book or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", book):
        raise PipelineError("book 必须只包含字母、数字、下划线或短横线，且以字母/数字开头")
    return book


def resolve_books_dir(value: Optional[str]) -> Path:
    raw = value or os.environ.get("ALEXANDRIA_BOOKS_DIR")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_BOOKS_DIR


def book_root(books_dir: Path, book: str) -> Path:
    return books_dir / validate_book_id(book)


def chapter_root(book_dir: Path, chapter: int) -> Path:
    return book_dir / "chapters" / f"{chapter:06d}"


def load_book(book_dir: Path) -> Dict[str, Any]:
    manifest = read_json(book_dir / "book.json")
    if not isinstance(manifest, dict):
        raise PipelineError(f"找不到有效的书籍项目：{book_dir / 'book.json'}，请先运行 init")
    return manifest


def load_config() -> Dict[str, Any]:
    configured = os.environ.get("ALEXANDRIA_CONFIG_PATH")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend([APP_DIR / "config.json", APP_DIR / "config.example.json"])
    for path in candidates:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                continue
    return {
        "tts": {
            "mode": os.environ.get("ALEXANDRIA_TTS_MODE", "external"),
            "url": "http://127.0.0.1:18000/tts",
            "urls": [
                "http://127.0.0.1:18000/tts",
                "http://127.0.0.1:18001/tts",
            ],
            "external_batch_size": 48,
            "voice_profile_urls": [
                "http://127.0.0.1:18000/voice_profiles/design",
                "http://127.0.0.1:18001/voice_profiles/design",
            ],
            "voice_profile_timeout": 900,
            "voice_profile_required": True,
            "device": os.environ.get("ALEXANDRIA_TTS_DEVICE", "auto"),
            "language": os.environ.get("ALEXANDRIA_TTS_LANGUAGE", "Chinese"),
            "parallel_workers": 2,
        }
    }


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    """Small dependency-free HTML-to-text converter for EPUB XHTML files."""

    BLOCK_TAGS = {
        "p", "div", "br", "body", "section", "article", "h1", "h2", "h3",
        "h4", "h5", "h6", "li", "blockquote", "title", "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        value = value.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n[ \t]+", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _epub_spine_paths(zf: zipfile.ZipFile) -> List[str]:
    """Return EPUB XHTML paths in OPF spine order when the metadata is valid."""
    def elements(root: ET.Element, local_name: str) -> Iterable[ET.Element]:
        return (element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == local_name)

    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = next(iter(elements(container, "rootfile")))
        opf_path = rootfile.attrib["full-path"]
        opf_dir = str(Path(opf_path).parent)
        if opf_dir == ".":
            opf_dir = ""
        opf = ET.fromstring(zf.read(opf_path))
        manifest: Dict[str, str] = {}
        for item in elements(opf, "item"):
            href = unquote(item.attrib.get("href", "").split("#", 1)[0])
            media_type = item.attrib.get("media-type", "")
            if "html" in media_type or href.lower().endswith((".xhtml", ".html", ".htm")):
                manifest[item.attrib.get("id", "")] = posixpath.normpath(posixpath.join(opf_dir, href))
        ordered = []
        for itemref in elements(opf, "itemref"):
            href = manifest.get(itemref.attrib.get("idref", ""))
            if href and href in zf.namelist():
                ordered.append(href)
        if ordered:
            return ordered
    except (KeyError, ET.ParseError, OSError, AttributeError, StopIteration):
        pass
    return sorted(
        name for name in zf.namelist()
        if name.lower().endswith((".xhtml", ".html", ".htm")) and not name.endswith("/")
    )


def _read_epub(path: Path) -> str:
    sections: List[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in _epub_spine_paths(zf):
            try:
                parser = _TextExtractor()
                parser.feed(zf.read(name).decode("utf-8", errors="replace"))
                text = parser.text()
            except (KeyError, UnicodeError):
                continue
            if text:
                sections.append(text)
    return "\n\n".join(sections)


def read_book_input(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise PipelineError(f"输入文件不存在：{path}")
    if path.suffix.lower() == ".epub":
        text = _read_epub(path)
    else:
        text = _read_text_file(path)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # A few TXT exports contain the common CP1252-as-UTF8 artefacts.
    replacements = {"â€™": "'", "â€œ": '“', "â€\x9d": '”', "â€¦": "…"}
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text.strip()


CHAPTER_RE = re.compile(
    r"^\s*(?:(?:第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节回卷集篇部])|"
    r"(?:chapter|chap\.?|卷)\s*[0-9零〇一二三四五六七八九十百千万两]+)"
    r"[^\n]{0,120}\s*$",
    re.IGNORECASE,
)


def _looks_like_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and CHAPTER_RE.match(stripped))


def split_chapters(text: str) -> List[Tuple[str, str]]:
    """Split long-form text at chapter-heading lines.

    If no conventional headings are found, the input remains a single
    chapter.  We deliberately do not try to infer a knowledge graph or any
    other book structure here.
    """
    lines = text.splitlines()
    heading_indices = [i for i, line in enumerate(lines) if _looks_like_chapter_heading(line)]
    if not heading_indices:
        return [("Chapter 1", text.strip())] if text.strip() else []

    chapters: List[Tuple[str, str]] = []
    if heading_indices[0] > 0:
        preface = "\n".join(lines[:heading_indices[0]]).strip()
        if preface:
            chapters.append(("Preface", preface))
    for position, start in enumerate(heading_indices):
        end = heading_indices[position + 1] if position + 1 < len(heading_indices) else len(lines)
        heading = lines[start].strip()
        body = "\n".join(lines[start:end]).strip()
        if body:
            chapters.append((heading, body))
    return chapters


def split_natural(text: str, max_chars: int = 4000) -> List[str]:
    """Split a chapter without cutting through normal prose/dialogue."""
    text = text.strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    units: List[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue
        sentences = [s.strip() for s in re.split(r"(?<=[。！？!?；;…])\s*", paragraph) if s.strip()]
        if not sentences:
            sentences = [paragraph]
        for sentence in sentences:
            if len(sentence) <= max_chars:
                units.append(sentence)
            else:
                # An unusually long line: preserve all text while making the
                # least surprising cut possible at punctuation, then chars.
                for start in range(0, len(sentence), max_chars):
                    units.append(sentence[start:start + max_chars])

    chunks: List[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if current and len(candidate) > max_chars:
            chunks.append(current.strip())
            current = unit
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks


def title_for_chapter(book: Dict[str, Any], number: int) -> str:
    chapters = book.get("chapters", [])
    if 1 <= number <= len(chapters) and isinstance(chapters[number - 1], dict):
        return str(chapters[number - 1].get("title") or f"Chapter {number}")
    return f"Chapter {number}"


_CHINESE_NUMERAL_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_NUMERAL_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
    "亿": 100000000,
}
_ORIGINAL_CHAPTER_PREFIX_PATTERNS = (
    re.compile(
        r"^\s*第\s*(?P<number>[0-9零〇一二三四五六七八九十百千万两亿]+)\s*"
        r"(?:章|节|回|卷|集|篇|部)\s*(?P<title>.*?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:chapter|chap\.?)\s*(?P<number>[0-9]+)\s*"
        r"[-:：.、]?\s*(?P<title>.*?)\s*$",
        re.IGNORECASE,
    ),
)


def _parse_novel_chapter_number(value: str) -> Optional[int]:
    """Parse Arabic or common Chinese numerals used by the source novel."""
    value = str(value or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if any(char not in _CHINESE_NUMERAL_DIGITS and char not in _CHINESE_NUMERAL_UNITS for char in value):
        return None

    total = 0
    section = 0
    number = 0
    for char in value:
        if char in _CHINESE_NUMERAL_DIGITS:
            number = _CHINESE_NUMERAL_DIGITS[char]
            continue
        unit = _CHINESE_NUMERAL_UNITS[char]
        if unit < 10000:
            section += (number or 1) * unit
            number = 0
        else:
            section += number
            total += section * unit
            section = 0
            number = 0
    return total + section + number


def _split_original_chapter_title(value: str) -> Tuple[Optional[int], str]:
    for pattern in _ORIGINAL_CHAPTER_PREFIX_PATTERNS:
        match = pattern.match(str(value or ""))
        if match:
            return _parse_novel_chapter_number(match.group("number")), match.group("title").strip()
    return None, ""


def _title_from_chapter_source(book_dir: Path, number: int) -> str:
    """Recover a title stored on the line after a standalone chapter heading."""
    source_path = chapter_root(book_dir, number) / "source.txt"
    if not source_path.exists():
        return ""
    try:
        lines = [line.strip() for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return ""
    for line in lines[:4]:
        _, inline_title = _split_original_chapter_title(line)
        if inline_title:
            return inline_title
        if _looks_like_chapter_heading(line):
            continue
        # Avoid mistaking the first sentence of a chapter for its title.
        if len(line) <= 80 and not re.search(r"[。！？!?；;]$", line):
            return line
        break
    return ""


def _safe_filename_component(value: str, fallback: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", "-", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or fallback


_ARC_ALIASES = {
    "main": "main",
    "正文": "main",
    "主线": "main",
    "xian": "xian",
    "xianjie": "xian",
    "仙": "xian",
    "仙界": "xian",
    "仙界篇": "xian",
    "outside": "outside",
    "wai": "outside",
    "外": "outside",
    "外传": "outside",
}
_ARC_DISPLAY_NAMES = {
    "main": "正文",
    "xian": "仙界篇",
    "outside": "外传",
}
_ARC_FILENAME_PREFIXES = {
    "main": "正",
    "xian": "仙",
    "outside": "外",
}
_ARC_ORDER = ("main", "xian", "outside")


def normalize_arc(value: str = "main") -> str:
    key = str(value or "main").strip().lower()
    normalized = _ARC_ALIASES.get(key)
    if normalized is None:
        raise PipelineError(
            f"未知章节分区：{value}；可用值为 main、xian/仙界篇、outside/外传"
        )
    return normalized


def arc_display_name(arc: str) -> str:
    return _ARC_DISPLAY_NAMES[normalize_arc(arc)]


def chapter_display_label(arc: str, number: int) -> str:
    arc = normalize_arc(arc)
    if arc == "main":
        return f"小说第 {number} 章"
    return f"{arc_display_name(arc)}第 {number} 章"


def chapter_audio_filename(
    book_dir: Path,
    book: Dict[str, Any],
    number: int,
    arc: str = "main",
    novel_number: Optional[int] = None,
) -> str:
    """Return the stable ABS filename based on the novel's original chapter."""
    arc = normalize_arc(arc)
    original_heading = title_for_chapter(book, number)
    original_number, chapter_title = _split_original_chapter_title(original_heading)
    if not chapter_title:
        chapter_title = _title_from_chapter_source(book_dir, number)
    if novel_number is not None:
        original_number = int(novel_number)
    if original_number is None:
        original_number = number
    if not chapter_title:
        chapter_title = original_heading or f"Chapter {original_number}"
    chapter_title = _safe_filename_component(chapter_title, f"Chapter {original_number}")
    prefix = _ARC_FILENAME_PREFIXES[arc]
    return f"{prefix}_{original_number}_{chapter_title}{CHAPTER_AUDIO_SUFFIX}"


_NOVEL_INDEX_VERSION = 4
_NARRATIVE_MIN_CHARS = 80
_NARRATIVE_SECTION_MARKERS = (
    "目录",
    "附录",
    "APPENDIX",
    "凡人相关文章",
    "凡人修仙传仙界篇",
    "凡人修仙传外传",
)


def _chapter_manifest_fingerprint(book: Dict[str, Any]) -> str:
    payload = {
        "source_sha256": book.get("source_sha256"),
        "chapters": book.get("chapters", []),
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _is_narrative_chapter_candidate(book_dir: Path, item: Dict[str, Any]) -> bool:
    """Reject TOC/heading-only entries before building the public chapter map."""
    try:
        internal = int(item.get("number"))
        source_chars = int(item.get("source_chars") or 0)
    except (TypeError, ValueError):
        return False
    if internal <= 0 or source_chars < _NARRATIVE_MIN_CHARS:
        return False
    source_path = chapter_root(book_dir, internal) / "source.txt"
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError:
        return False
    leading_lines = [line.strip() for line in text.splitlines() if line.strip()][:16]
    for line in leading_lines:
        normalized = re.sub(r"\s+", "", line)
        if normalized.upper() == "APPENDIX" or normalized in _NARRATIVE_SECTION_MARKERS:
            return False
        if normalized.startswith(("凡人修仙传仙界篇", "凡人修仙传外传", "凡人相关文章")):
            return False
    return bool(re.search(r"[。！？!?；;，,]", text))


def _valid_novel_chapter_index(mapping: Dict[int, int]) -> bool:
    if not mapping:
        return False
    numbers = sorted(mapping)
    if numbers != list(range(1, numbers[-1] + 1)):
        return False
    internal_numbers = list(mapping.values())
    return len(internal_numbers) == len(set(internal_numbers)) and all(number > 0 for number in internal_numbers)


def _contiguous_chapter_runs(candidates: List[Tuple[int, int]]) -> List[List[Tuple[int, int]]]:
    """Group runs with consecutive public numbers and ordered source records."""
    runs: List[List[Tuple[int, int]]] = []
    current: List[Tuple[int, int]] = []
    for candidate in candidates:
        if current:
            previous_public, previous_internal = current[-1]
            public_number, internal_number = candidate
            if public_number == previous_public + 1 and internal_number > previous_internal:
                current.append(candidate)
                continue
            runs.append(current)
        current = [candidate]
    if current:
        runs.append(current)
    return runs


def _candidate_chapters(book_dir: Path, book: Dict[str, Any]) -> List[Tuple[int, int]]:
    candidates: List[Tuple[int, int]] = []
    for item in book.get("chapters", []):
        if not isinstance(item, dict) or not _is_narrative_chapter_candidate(book_dir, item):
            continue
        novel_number, _ = _split_original_chapter_title(str(item.get("title") or ""))
        if novel_number is None or novel_number <= 0:
            continue
        candidates.append((novel_number, int(item["number"])))
    return candidates


def _run_to_mapping(run: List[Tuple[int, int]]) -> Dict[int, int]:
    mapping = {novel_number: internal_number for novel_number, internal_number in run}
    if not _valid_novel_chapter_index(mapping):
        return {}
    return mapping


def _build_novel_chapter_maps(book_dir: Path, book: Dict[str, Any]) -> Dict[str, Dict[int, int]]:
    """Build strict maps for the main novel and its two appended arcs.

    The imported manifest has a long main-body run followed by a short
    仙界篇 run and an 外传 run.  Only those ordered, contiguous runs are
    public; unrelated appended records remain intentionally unreachable.
    """
    candidates = _candidate_chapters(book_dir, book)
    runs = _contiguous_chapter_runs(candidates)
    if not runs:
        raise PipelineError("无法严格识别小说正文章节：没有正文候选")
    main_run = max(runs, key=len)
    main = _run_to_mapping(main_run)
    if len(main) < 3:
        raise PipelineError(
            "无法严格识别小说正文章节：正文候选没有形成从第 1 章开始的连续序列；"
            "已拒绝把目录、标题行或附录当成章节"
        )

    maps: Dict[str, Dict[int, int]] = {"main": main}
    main_last_internal = max(main.values())
    appended_candidates = [candidate for candidate in candidates if candidate[1] > main_last_internal]
    appended_runs = _contiguous_chapter_runs(appended_candidates)
    side_runs = [
        run for run in appended_runs
        if run and run[0][0] == 1 and _run_to_mapping(run)
    ]
    for arc, run in zip(("xian", "outside"), side_runs[:2]):
        maps[arc] = _run_to_mapping(run)
    return maps


def _valid_novel_chapter_maps(maps: Dict[str, Dict[int, int]]) -> bool:
    if "main" not in maps or not _valid_novel_chapter_index(maps["main"]):
        return False
    used_internal: set[int] = set()
    for arc, mapping in maps.items():
        if arc not in _ARC_ORDER or not _valid_novel_chapter_index(mapping):
            return False
        if used_internal.intersection(mapping.values()):
            return False
        used_internal.update(mapping.values())
    return True


def _mapping_sources_exist(book_dir: Path, maps: Dict[str, Dict[int, int]]) -> bool:
    return all(
        (chapter_root(book_dir, internal_number) / "source.txt").exists()
        for mapping in maps.values()
        for internal_number in mapping.values()
    )


def novel_chapter_maps(book_dir: Path, book: Dict[str, Any]) -> Dict[str, Dict[int, int]]:
    """Return cached, validated public maps for all supported arcs."""
    fingerprint = _chapter_manifest_fingerprint(book)
    cache_path = book_dir / "state" / "novel_chapters.json"
    cached = read_json(cache_path, None)
    if (
        isinstance(cached, dict)
        and cached.get("version") == _NOVEL_INDEX_VERSION
        and cached.get("manifest_fingerprint") == fingerprint
        and isinstance(cached.get("arcs"), dict)
    ):
        raw_arcs = cached["arcs"]
        maps: Dict[str, Dict[int, int]] = {}
        for arc, raw_mapping in raw_arcs.items():
            if not isinstance(raw_mapping, dict):
                maps = {}
                break
            try:
                maps[normalize_arc(arc)] = {int(key): int(value) for key, value in raw_mapping.items()}
            except (TypeError, ValueError, PipelineError):
                maps = {}
                break
        if maps and _valid_novel_chapter_maps(maps) and _mapping_sources_exist(book_dir, maps):
            return maps

    maps = _build_novel_chapter_maps(book_dir, book)
    atomic_write_json(
        cache_path,
        {
            "version": _NOVEL_INDEX_VERSION,
            "manifest_fingerprint": fingerprint,
            "arcs": {
                arc: {str(key): value for key, value in mapping.items()}
                for arc, mapping in maps.items()
            },
            # Keep the main map at a predictable key for simple external tools.
            "chapters": {str(key): value for key, value in maps["main"].items()},
            "updated_at": now_iso(),
        },
    )
    return maps


def novel_chapter_index(book_dir: Path, book: Dict[str, Any]) -> Dict[int, int]:
    """Backward-compatible accessor for the main novel map."""
    return novel_chapter_maps(book_dir, book)["main"]


def available_novel_chapters(book_dir: Path, book: Dict[str, Any], arc: str = "main") -> List[int]:
    arc = normalize_arc(arc)
    maps = novel_chapter_maps(book_dir, book)
    if arc not in maps:
        raise PipelineError(f"没有识别出{arc_display_name(arc)}正文")
    return sorted(maps[arc])


def init_project(
    books_dir: Path,
    book_id: str,
    input_path: Path,
    title: Optional[str] = None,
    force: bool = False,
    codex_model: Optional[str] = None,
) -> Path:
    book_id = validate_book_id(book_id)
    input_path = input_path.expanduser().resolve()
    text = read_book_input(input_path)
    chapters = split_chapters(text)
    if not chapters:
        raise PipelineError("输入文件没有可用文本")
    target = book_root(books_dir, book_id)
    if target.exists() and not force:
        raise PipelineError(f"书籍项目已存在：{target}；如需覆盖请显式使用 --force")
    target.mkdir(parents=True, exist_ok=True)
    (target / "chapters").mkdir(exist_ok=True)
    # Re-initializing with --force replaces only generated chapter/state data;
    # the original input file is never deleted.
    for child in (target / "chapters", target / "state", target / "cache", target / "output"):
        if child.exists():
            shutil.rmtree(child)
    ensure_project_state(target)
    chapter_manifest: List[Dict[str, Any]] = []
    for number, (chapter_title, chapter_text) in enumerate(chapters, 1):
        chapter_dir = chapter_root(target, number)
        chapter_dir.mkdir(parents=True, exist_ok=True)
        source_path = chapter_dir / "source.txt"
        source_path.write_text(chapter_text.strip() + "\n", encoding="utf-8")
        atomic_write_json(chapter_dir / "status.json", default_chapter_status(number, sha256_file(source_path)))
        chapter_manifest.append({
            "number": number,
            "title": chapter_title,
            "source_sha256": sha256_file(source_path),
            "source_chars": len(chapter_text),
        })
    book_manifest = {
        "schema_version": SCHEMA_VERSION,
        "book_id": book_id,
        "title": title or book_id,
        "source_path": str(input_path),
        "source_sha256": sha256_file(input_path),
        "prompt_version": PROMPT_VERSION,
        "codex_model": str(codex_model or os.environ.get("ALEXANDRIA_CODEX_MODEL") or DEFAULT_CODEX_MODEL).strip(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "chapter_count": len(chapter_manifest),
        "chapters": chapter_manifest,
    }
    atomic_write_json(target / "book.json", book_manifest)
    print(f"initialized {book_id}: {len(chapter_manifest)} chapters -> {target}")
    return target


def available_chapters(book: Dict[str, Any]) -> List[int]:
    return [int(item["number"]) for item in book.get("chapters", []) if isinstance(item, dict) and item.get("number")]


def select_chapters(
    book: Dict[str, Any],
    chapter: Optional[int] = None,
    first: Optional[int] = None,
    last: Optional[int] = None,
    count: Optional[int] = None,
    continue_: bool = False,
    book_dir: Optional[Path] = None,
    arc: str = "main",
) -> List[int]:
    if book_dir is None:
        raise PipelineError("章节选择需要 book_dir，不能绕过正文章节映射")
    arc = normalize_arc(arc)
    maps = novel_chapter_maps(book_dir, book)
    mapping = maps.get(arc)
    if not mapping:
        raise PipelineError(f"没有识别出{arc_display_name(arc)}正文")
    novel_numbers = sorted(mapping)
    section_label = arc_display_name(arc)

    supplied_range_options = [value is not None for value in (first, last, count)]
    if chapter is not None:
        if any(supplied_range_options):
            raise PipelineError("--chapter 不能和 --from/--to/--count 同时使用")
        if chapter not in mapping:
            raise PipelineError(f"{section_label}第 {chapter} 章不存在（可用范围：1-{max(novel_numbers)}）")
        requested_novel_numbers = [chapter]
    else:
        if count is not None:
            if count <= 0:
                raise PipelineError("--count 必须是正整数")
            if last is not None:
                raise PipelineError("--count 不能和 --to 同时使用")
        start = first if first is not None else min(novel_numbers)
        if count is not None:
            end = start + count - 1
        else:
            end = last if last is not None else max(novel_numbers)
        if start <= 0 or end < start:
            raise PipelineError(f"{section_label}章节范围无效")
        requested_novel_numbers = list(range(start, end + 1))
        missing = [number for number in requested_novel_numbers if number not in mapping]
        if missing:
            preview = ", ".join(str(number) for number in missing[:12])
            suffix = "..." if len(missing) > 12 else ""
            raise PipelineError(f"{section_label}章节不存在：{preview}{suffix}")

    if continue_:
        published_dir = book_dir / "output" / "chapters"
        for position, novel_number in enumerate(requested_novel_numbers):
            internal_number = mapping[novel_number]
            status = load_chapter_status(book_dir, internal_number)
            audio_exists = (chapter_root(book_dir, internal_number) / f"audio{CHAPTER_AUDIO_SUFFIX}").exists()
            published_exists = (
                published_dir
                / chapter_audio_filename(
                    book_dir, book, internal_number, arc=arc, novel_number=novel_number
                )
            ).exists()
            if not status.get("done") or not audio_exists or not published_exists:
                return [mapping[number] for number in requested_novel_numbers[position:]]
        return []
    return [mapping[number] for number in requested_novel_numbers]


def print_status(book_dir: Path, as_json: bool = False) -> None:
    book = load_book(book_dir)
    maps = novel_chapter_maps(book_dir, book)
    rows: List[Dict[str, Any]] = []
    for arc in _ARC_ORDER:
        mapping = maps.get(arc, {})
        for novel_number in sorted(mapping):
            internal_number = mapping[novel_number]
            status = load_chapter_status(book_dir, internal_number)
            rows.append({
                "arc": arc,
                "arc_name": arc_display_name(arc),
                "chapter": novel_number,
                "title": title_for_chapter(book, internal_number),
                "analysis": bool(status.get("analysis")),
                "summary": bool(status.get("summary")),
                "voices": bool(status.get("voices")),
                "tts": bool(status.get("tts")),
                "done": bool(status.get("done")),
                "analysis_chunks_done": int(status.get("analysis_chunks_done", 0)),
                "tts_lines_done": int(status.get("tts_lines_done", 0)),
            })
    summary = {
        "book": book.get("book_id"),
        "title": book.get("title"),
        "chapters": len(rows),
        "arcs": {arc: len(maps.get(arc, {})) for arc in _ARC_ORDER if arc in maps},
        "done": sum(1 for row in rows if row["done"]),
        "analysis": sum(1 for row in rows if row["analysis"]),
        "tts": sum(1 for row in rows if row["tts"]),
        "rows": rows,
    }
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print(f"{summary['title']} ({summary['book']})")
    arc_summary = " | ".join(
        f"{arc_display_name(arc)}: {summary['arcs'].get(arc, 0)}"
        for arc in _ARC_ORDER
        if arc in summary["arcs"]
    )
    print(
        f"chapters: {summary['chapters']} ({arc_summary}) | "
        f"analysis: {summary['analysis']} | tts: {summary['tts']} | done: {summary['done']}"
    )
    print("ARC  NOVEL_CHAPTER  ANALYSIS  VOICES  TTS  DONE  TITLE")
    for row in rows:
        flags = "  ".join("✓" if row[key] else "-" for key in ("analysis", "voices", "tts", "done"))
        print(
            f"{row['arc']:<7} {row['chapter']:>5}  {flags:<22}  "
            f"{row['title'][:60]}"
        )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def _pipeline_from_args(args: argparse.Namespace) -> BookPipeline:
    directory = book_root(resolve_books_dir(getattr(args, "books_dir", None)), args.book)
    if not directory.exists():
        raise PipelineError(f"书籍项目不存在：{directory}；请先运行 init")
    return BookPipeline(directory)


def command_run(args: argparse.Namespace, analysis_only: bool = False, render_only: bool = False) -> int:
    pipeline = _pipeline_from_args(args)
    arc = normalize_arc(getattr(args, "arc", "main"))
    selected = select_chapters(
        pipeline.book,
        chapter=getattr(args, "chapter", None),
        first=getattr(args, "from_chapter", None),
        last=getattr(args, "to_chapter", None),
        count=getattr(args, "count", None),
        continue_=getattr(args, "continue_", False) and not getattr(args, "force", False),
        book_dir=pipeline.book_dir,
        arc=arc,
    )
    if not selected:
        print("没有需要继续处理的章节")
        return 0
    dry_run = bool(getattr(args, "dry_run", False))
    if dry_run and not render_only:
        print(f"codex model: {pipeline.codex.model} (dry-run，不调用 Codex/TTS)")
        for number in selected:
            status = load_chapter_status(pipeline.book_dir, number)
            print(
                f"{pipeline.chapter_label(number)}: "
                f"analysis={'done' if status.get('analysis') else 'pending'}, "
                f"summary={'done' if status.get('summary') else 'pending'}, "
                "audio=planned"
            )
        return 0
    if not render_only:
        print(f"codex model: {pipeline.codex.model}")
    for number in selected:
        chapter_label = pipeline.chapter_label(number)
        force = bool(getattr(args, "force", False))
        if not render_only:
            status = load_chapter_status(pipeline.book_dir, number)
            needs_analysis = force or not status.get("analysis") or not (chapter_root(pipeline.book_dir, number) / "script.json").exists()
            if needs_analysis:
                pipeline.analyze_chapter(number, force=force)
            needs_summary = force or not status.get("summary") or not (chapter_root(pipeline.book_dir, number) / "summary.txt").exists()
            if not analysis_only and needs_summary:
                pipeline.finalize_chapter(number, force=force)
            elif analysis_only and needs_summary:
                # analyze is intentionally analysis-only; summary remains a
                # separate finalize step in `run` so callers can inspect script.
                pass
        if analysis_only:
            continue
        if render_only or not analysis_only:
            pipeline.render_chapter(number, force=force, dry_run=dry_run)
            print(f"{chapter_label}: {'checked' if dry_run else 'DONE'}")
    return 0


def command_review(args: argparse.Namespace) -> int:
    pipeline = _pipeline_from_args(args)
    arc = normalize_arc(getattr(args, "arc", "main"))
    numbers = select_chapters(
        pipeline.book, chapter=args.chapter, first=None, last=None,
        book_dir=pipeline.book_dir, arc=arc
    )
    for number in numbers:
        pipeline.review_chapter(number, force=args.force)
        print(f"{pipeline.chapter_label(number)}: reviewed (TTS invalidated)")
    return 0


def command_character(args: argparse.Namespace) -> int:
    if not getattr(args, "book", None):
        raise PipelineError("character 命令需要 --book")
    pipeline = _pipeline_from_args(args)
    action = args.character_command
    if action == "list":
        for character_id, record in pipeline.character_list():
            print(json.dumps({"character_id": character_id, **record}, ensure_ascii=False))
        return 0
    if action == "alias":
        pipeline.add_alias(args.character_id, args.alias)
        print(f"alias added: {args.alias} -> {args.character_id}")
        return 0
    if action == "merge":
        pipeline.merge_characters(args.source_id, args.target_id)
        print(f"merged: {args.source_id} -> {args.target_id}")
        return 0
    raise PipelineError(f"未知 character 子命令：{action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Alexandria 纯 CLI 长篇小说有声书流水线（Book → Chapter → Chunk）",
    )
    parser.add_argument("--books-dir", help="书籍项目根目录（默认 ./books，可用 ALEXANDRIA_BOOKS_DIR）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化 TXT/EPUB 书籍项目并拆分章节")
    init_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    init_parser.add_argument("--book", required=True)
    init_parser.add_argument("--input", required=True, help="TXT 或 EPUB 文件")
    init_parser.add_argument("--title", help="书名（默认使用 book ID）")
    init_parser.add_argument(
        "--codex-model",
        default=None,
        help=f"章节分析模型（默认 {DEFAULT_CODEX_MODEL}，也可用 ALEXANDRIA_CODEX_MODEL 覆盖）",
    )
    init_parser.add_argument("--force", action="store_true", help="覆盖已有生成状态")

    def add_range_options(command_parser: argparse.ArgumentParser, require_chapter: bool = False) -> None:
        command_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        command_parser.add_argument("--book", required=True)
        command_parser.add_argument("--arc", default="main", help="章节分区：main、xian/仙界篇、outside/外传")
        command_parser.add_argument("--chapter", type=int, required=require_chapter, help="分区内小说原始章节号")
        command_parser.add_argument("--from", dest="from_chapter", type=int, help="起始小说章节号")
        command_parser.add_argument("--to", dest="to_chapter", type=int, help="结束小说章节号（包含）")
        command_parser.add_argument("--count", type=int, help="从 --from 起连续处理 N 个小说章节（包含起始章）")
        command_parser.add_argument("--continue", dest="continue_", action="store_true", help="从范围内第一个未完成的小说章节继续")
        command_parser.add_argument("--force", action="store_true", help="忽略分析/TTS缓存")

    run_parser = subparsers.add_parser("run", help="按小说章节分析、摘要并渲染音频")
    add_range_options(run_parser)
    run_parser.add_argument("--dry-run", action="store_true", help="只验证流程，不加载 TTS 模型")

    analyze_parser = subparsers.add_parser("analyze", help="只运行指定小说章节的 Codex 分析和人物状态更新")
    add_range_options(analyze_parser)

    render_parser = subparsers.add_parser("render", help="只读取已有 script.json 并生成小说章节音频")
    add_range_options(render_parser)
    render_parser.add_argument("--dry-run", action="store_true", help="只检查待渲染行，不加载 TTS 模型")

    review_parser = subparsers.add_parser("review", help="手动调用一次 Codex 审校指定小说章节（默认不自动运行）")
    review_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    review_parser.add_argument("--book", required=True)
    review_parser.add_argument("--arc", default="main", help="章节分区：main、xian/仙界篇、outside/外传")
    review_parser.add_argument("--chapter", type=int, required=True, help="分区内小说原始章节号")
    review_parser.add_argument("--force", action="store_true")

    status_parser = subparsers.add_parser("status", help="查看章节状态")
    status_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    status_parser.add_argument("--book", required=True)
    status_parser.add_argument("--json", action="store_true", dest="as_json")

    export_parser = subparsers.add_parser("export", help="将章节 M4B 导出为带章节标记的 m4b")
    export_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    export_parser.add_argument("--book", required=True)
    export_parser.add_argument("--arc", default="main", help="章节分区：main、xian/仙界篇、outside/外传")
    export_parser.add_argument("--format", choices=["m4b"], default="m4b")
    export_parser.add_argument("--from", dest="from_chapter", type=int)
    export_parser.add_argument("--to", dest="to_chapter", type=int)

    character_parser = subparsers.add_parser("character", help="查看和修正人物/别名状态")
    character_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    character_parser.add_argument("--book", required=False)
    character_sub = character_parser.add_subparsers(dest="character_command", required=True)
    list_character_parser = character_sub.add_parser("list", help="列出人物")
    list_character_parser.add_argument("--book", dest="book", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    list_character_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    merge_parser = character_sub.add_parser("merge", help="将 SOURCE 合并到 TARGET")
    merge_parser.add_argument("--book", dest="book", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    merge_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    merge_parser.add_argument("source_id")
    merge_parser.add_argument("target_id")
    alias_parser = character_sub.add_parser("alias", help="为人物添加人工别名")
    alias_parser.add_argument("--book", dest="book", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    alias_parser.add_argument("--books-dir", dest="books_dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    alias_parser.add_argument("character_id")
    alias_parser.add_argument("alias")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_project(
                resolve_books_dir(args.books_dir),
                args.book,
                Path(args.input),
                args.title,
                args.force,
                args.codex_model,
            )
            return 0
        if args.command == "status":
            directory = book_root(resolve_books_dir(args.books_dir), args.book)
            print_status(directory, args.as_json)
            return 0
        if args.command == "export":
            pipeline = _pipeline_from_args(args)
            output = pipeline.export_m4b(args.from_chapter, args.to_chapter, args.arc)
            print(f"exported: {output}")
            return 0
        if args.command == "character":
            return command_character(args)
        if args.command == "review":
            return command_review(args)
        if args.command == "analyze":
            return command_run(args, analysis_only=True)
        if args.command == "render":
            return command_run(args, render_only=True)
        if args.command == "run":
            return command_run(args)
        parser.error(f"unknown command: {args.command}")
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已中断；下次运行 run --continue 可从断点继续", file=sys.stderr)
        return 130
    return 0


# ---------------------------------------------------------------------------
# Codex bridge and persistent project state
# ---------------------------------------------------------------------------


def _generic_voice_id(gender: str = "male", age: str = "middle") -> str:
    gender = str(gender or "male").lower()
    age = str(age or "middle").lower()
    if any(token in gender for token in ("female", "woman", "girl", "女")):
        gender = "female"
    else:
        gender = "male"
    if any(token in age for token in ("young", "少年", "青年", "child", "teen")):
        age = "young"
    elif any(token in age for token in ("old", "elder", "老年", "老人")):
        age = "old"
    else:
        age = "middle"
    return f"voice_generic_{gender}_{age}"


GENERIC_VOICE_CHOICES = {
    "voice_generic_male_young": ("Ryan", "young male, clear and natural"),
    "voice_generic_male_middle": ("Aiden", "middle-aged male, steady and natural"),
    "voice_generic_male_old": ("Uncle_fu", "older male, warm and measured"),
    "voice_generic_female_young": ("Vivian", "young female, clear and lively"),
    "voice_generic_female_middle": ("Serena", "middle-aged female, calm and warm"),
    "voice_generic_female_old": ("Sohee", "older female, gentle and measured"),
}


def default_voices() -> Dict[str, Dict[str, Any]]:
    voices: Dict[str, Dict[str, Any]] = {
        "voice_narrator": {
            "voice_id": "voice_narrator",
            "character_id": None,
            "voice_type": "narrator",
            "type": "custom",
            "voice": "Aiden",
            "style": "deep, calm, measured male narrator with a restrained classical xianxia tone",
            "locked": True,
        }
    }
    for voice_id, (voice, style) in GENERIC_VOICE_CHOICES.items():
        voices[voice_id] = {
            "voice_id": voice_id,
            "character_id": None,
            "voice_type": "generic",
            "type": "custom",
            "voice": voice,
            "style": style,
            "locked": True,
        }
    return voices


def ensure_project_state(book_dir: Path) -> None:
    state_dir = book_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    if not (state_dir / "characters.json").exists():
        atomic_write_json(state_dir / "characters.json", {})
    if not (state_dir / "aliases.json").exists():
        atomic_write_json(state_dir / "aliases.json", {})
    if not (state_dir / "voices.json").exists():
        atomic_write_json(state_dir / "voices.json", default_voices())
    (book_dir / "cache").mkdir(exist_ok=True)
    (book_dir / "output" / "chapters").mkdir(parents=True, exist_ok=True)


def load_state(book_dir: Path) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    ensure_project_state(book_dir)
    characters = read_json(book_dir / "state" / "characters.json", {})
    aliases = read_json(book_dir / "state" / "aliases.json", {})
    voices = read_json(book_dir / "state" / "voices.json", default_voices())
    if not isinstance(characters, dict) or not isinstance(aliases, dict) or not isinstance(voices, dict):
        raise PipelineError("state/ 下的 characters.json、aliases.json、voices.json 必须是 JSON 对象")
    return characters, {str(k): str(v) for k, v in aliases.items()}, voices


def save_state(book_dir: Path, characters: Dict[str, Any], aliases: Dict[str, str], voices: Dict[str, Any]) -> None:
    state_dir = book_dir / "state"
    atomic_write_json(state_dir / "characters.json", characters)
    atomic_write_json(state_dir / "aliases.json", aliases)
    atomic_write_json(state_dir / "voices.json", voices)


def chapter_status_path(book_dir: Path, number: int) -> Path:
    return chapter_root(book_dir, number) / "status.json"


def default_chapter_status(number: int, source_hash: str) -> Dict[str, Any]:
    return {
        "chapter": number,
        "source_sha256": source_hash,
        "prompt_version": PROMPT_VERSION,
        "analysis": False,
        "analysis_chunks_done": 0,
        "summary": False,
        "voices": False,
        "tts": False,
        "tts_lines_done": 0,
        "done": False,
        "updated_at": now_iso(),
    }


def load_chapter_status(book_dir: Path, number: int) -> Dict[str, Any]:
    chapter_dir = chapter_root(book_dir, number)
    source_path = chapter_dir / "source.txt"
    if not source_path.exists():
        raise PipelineError(f"第 {number} 章不存在：{source_path}")
    source_hash = sha256_file(source_path)
    status = read_json(chapter_dir / "status.json", None)
    if not isinstance(status, dict) or status.get("source_sha256") != source_hash:
        status = default_chapter_status(number, source_hash)
    elif status.get("prompt_version") != PROMPT_VERSION:
        # A prompt version change makes existing analysis stale, but does not
        # delete old files; --force can explicitly replace it.
        if status.get("analysis"):
            status["analysis"] = False
            status["summary"] = False
            status["voices"] = False
            status["tts"] = False
            status["done"] = False
            status["analysis_chunks_done"] = 0
            status["tts_lines_done"] = 0
        status["prompt_version"] = PROMPT_VERSION
    status.setdefault("summary", bool((chapter_dir / "summary.txt").exists()))
    status.setdefault("analysis_chunks_done", 0)
    status.setdefault("tts_lines_done", 0)
    if status.get("analysis") and not (chapter_dir / "script.json").exists():
        status["analysis"] = False
        status["summary"] = False
        status["voices"] = False
        status["tts"] = False
        status["done"] = False
    if status.get("summary") and not (chapter_dir / "summary.txt").exists():
        status["summary"] = False
    current_audio = chapter_dir / f"audio{CHAPTER_AUDIO_SUFFIX}"
    legacy_audio = chapter_dir / f"audio{LEGACY_CHAPTER_AUDIO_SUFFIX}"
    if status.get("tts") and not current_audio.exists() and not legacy_audio.exists():
        status["tts"] = False
        status["done"] = False
    status["updated_at"] = now_iso()
    atomic_write_json(chapter_dir / "status.json", status)
    return status


def save_chapter_status(book_dir: Path, number: int, status: Dict[str, Any]) -> None:
    status["updated_at"] = now_iso()
    atomic_write_json(chapter_status_path(book_dir, number), status)


def _next_id(prefix: str, values: Iterable[str], width: int = 6) -> str:
    highest = 0
    for value in values:
        match = re.fullmatch(re.escape(prefix) + r"(\d+)", str(value))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:0{width}d}"


def _voice_choice(voice_id: str) -> str:
    choices = ["Ryan", "Dylan", "Eric", "Ono_anna", "Ryan", "Serena", "Sohee", "Uncle_fu", "Vivian"]
    match = re.search(r"(\d+)$", voice_id)
    index = int(match.group(1)) if match else 0
    return choices[index % len(choices)]


def _is_unnamed(name: str, data: Optional[Dict[str, Any]] = None) -> bool:
    data = data or {}
    if data.get("named") is False or data.get("is_named") is False:
        return True
    value = str(name or "").strip()
    if not value:
        return True
    if data.get("named") is True or data.get("is_named") is True:
        return False
    return bool(re.search(r"(?:路人|弟子[甲乙丙丁戊己]?|守卫|侍卫|店小二|伙计|仆人|丫鬟|村民|男子|女子|老者|老人|少年甲|少女甲)", value))


class CodexRunner:
    """Run one isolated, read-only Codex analysis request."""

    def __init__(self, book_dir: Path, model: Optional[str] = None) -> None:
        self.book_dir = book_dir
        self.model = str(os.environ.get("ALEXANDRIA_CODEX_MODEL") or model or DEFAULT_CODEX_MODEL).strip()
        requested_effort = str(os.environ.get("ALEXANDRIA_CODEX_REASONING_EFFORT", "xhigh")).strip().lower()
        # Codex CLI calls this level xhigh; older project docs used max.
        if requested_effort == "max":
            requested_effort = "xhigh"
        self.reasoning_effort = requested_effort if requested_effort in {"low", "medium", "high", "xhigh"} else "high"
        configured = os.environ.get("ALEXANDRIA_CODEX_BIN", "codex")
        self.executable = shlex.split(configured)
        if not self.executable:
            self.executable = ["codex"]

    @staticmethod
    def _extract_json(text: str) -> Any:
        text = str(text or "").strip()
        if not text:
            raise PipelineError("Codex 返回为空")
        candidates = [text]
        if "```" in text:
            candidates.extend(re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE))
        # The output file normally contains exactly one JSON object.  The
        # fallback scans balanced braces to tolerate a small amount of prose.
        for candidate in candidates:
            try:
                return json.loads(candidate.strip())
            except json.JSONDecodeError:
                pass
        for start, char in enumerate(text):
            if char not in "[{":
                continue
            opener, closer = char, "]" if char == "[" else "}"
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(text)):
                current = text[index]
                if escaped:
                    escaped = False
                    continue
                if current == "\\" and in_string:
                    escaped = True
                    continue
                if current == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if current == opener:
                    depth += 1
                elif current == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:index + 1])
                        except json.JSONDecodeError:
                            break
        raise PipelineError(f"无法解析 Codex JSON 返回：{text[:500]}")

    def run(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        # Test harnesses and offline development can provide a deterministic
        # response without weakening the normal Codex path.
        fake = os.environ.get("ALEXANDRIA_FAKE_CODEX_RESPONSE")
        if fake:
            value = self._extract_json(fake)
            if not isinstance(value, dict):
                raise PipelineError("ALEXANDRIA_FAKE_CODEX_RESPONSE 必须是 JSON 对象")
            return value

        cache_dir = self.book_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        schema_path = cache_dir / f".codex_schema_{os.getpid()}.json"
        output_path = cache_dir / f".codex_output_{os.getpid()}.json"
        atomic_write_json(schema_path, schema)
        command = self.executable + [
            "exec", "--config", f'model_reasoning_effort="{self.reasoning_effort}"',
            "--model", self.model, "--ephemeral", "--sandbox", "read-only",
            "--output-schema", str(schema_path),
            "--output-last-message", str(output_path),
            "--cd", str(self.book_dir), "--skip-git-repo-check", "-",
        ]
        try:
            result = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=CODEX_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            raise PipelineError("找不到 codex 命令，请先安装并完成 codex auth login") from exc
        except subprocess.TimeoutExpired as exc:
            raise PipelineError(f"Codex 分析超时（>{CODEX_TIMEOUT_SECONDS}s）") from exc
        finally:
            try:
                schema_path.unlink()
            except FileNotFoundError:
                pass

        output = ""
        if output_path.exists():
            output = output_path.read_text(encoding="utf-8", errors="replace")
            try:
                output_path.unlink()
            except OSError:
                pass
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise PipelineError(f"Codex 执行失败（exit {result.returncode}）：{detail[-1200:]}")
        if not output:
            output = result.stdout
        value = self._extract_json(output)
        if not isinstance(value, dict):
            raise PipelineError("Codex 返回必须是 JSON 对象")
        return value


SCRIPT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["script", "new_characters", "possible_aliases"],
    "properties": {
        "script": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["speaker", "character_id", "text", "emotion"],
                "properties": {
                    "speaker": {"type": "string"},
                    "character_id": {"type": ["string", "null"]},
                    "text": {"type": "string"},
                    "emotion": {"type": "string"},
                },
            },
        },
        "new_characters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "gender", "age", "voice_character", "confidence", "named"],
                "properties": {
                    "name": {"type": "string"},
                    "gender": {"type": "string"},
                    "age": {"type": "string"},
                    "voice_character": {"type": "string"},
                    "confidence": {"type": "number"},
                    "named": {"type": "boolean"},
                },
            },
        },
        "possible_aliases": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "character_id", "confidence"],
                "properties": {
                    "name": {"type": "string"},
                    "character_id": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
    },
}


SUMMARY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "character_updates"],
    "properties": {
        "summary": {"type": "string"},
        "character_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["character_id", "description_append"],
                "properties": {
                    "character_id": {"type": "string"},
                    "description_append": {"type": "string"},
                },
            },
        },
    },
}


class _FakeTTSEngine:
    """Tiny opt-in renderer used for CLI smoke tests without model weights."""

    def ensure_voice_profile(self, voice_profile_id: str, description: str, sample_text: str, language: str = "Chinese", seed: int = -1) -> Dict[str, Any]:
        return {"voice_profile_id": voice_profile_id, "status": "ready", "cached": True}

    def generate_voice(self, text: str, instruct: str, speaker: str, voice_config: Dict[str, Any], output_path: str) -> bool:
        duration_ms = max(250, min(8000, 220 + len(text) * 28))
        sample_rate = 22050
        frames = int(sample_rate * duration_ms / 1000)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(output_path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(b"\x00\x00" * frames)
        return True



class BookPipeline:
    """File-backed state machine for one book project."""

    def __init__(self, book_dir: Path) -> None:
        self.book_dir = book_dir
        self.book = load_book(book_dir)
        ensure_project_state(book_dir)
        self.chapter_maps = novel_chapter_maps(book_dir, self.book)
        self.novel_index = self.chapter_maps["main"]
        self.internal_to_identity = {
            internal: (arc, novel)
            for arc, mapping in self.chapter_maps.items()
            for novel, internal in mapping.items()
        }
        self.internal_to_novel = {internal: novel for internal, (_, novel) in self.internal_to_identity.items()}
        self.characters, self.aliases, self.voices = load_state(book_dir)
        self.codex = CodexRunner(book_dir, self.book.get("codex_model"))

    @property
    def chapters_dir(self) -> Path:
        return self.book_dir / "chapters"

    def chapter_identity(self, internal_number: int) -> Tuple[str, int]:
        try:
            return self.internal_to_identity[int(internal_number)]
        except (KeyError, TypeError, ValueError) as exc:
            raise PipelineError("请求的章节不在已验证的小说正文映射中") from exc

    def chapter_arc(self, internal_number: int) -> str:
        return self.chapter_identity(internal_number)[0]

    def novel_chapter_number(self, internal_number: int) -> int:
        return self.chapter_identity(internal_number)[1]

    def chapter_label(self, internal_number: int) -> str:
        arc, novel_number = self.chapter_identity(internal_number)
        return chapter_display_label(arc, novel_number)

    def internal_chapter(self, novel_number: int, arc: str = "main") -> int:
        arc = normalize_arc(arc)
        mapping = self.chapter_maps.get(arc)
        if not mapping or int(novel_number) not in mapping:
            raise PipelineError(f"{arc_display_name(arc)}第 {novel_number} 章不存在")
        return mapping[int(novel_number)]

    def _previous_internal_chapter(self, internal_number: int) -> Optional[int]:
        arc, novel_number = self.chapter_identity(internal_number)
        mapping = self.chapter_maps[arc]
        if novel_number <= min(mapping):
            return None
        return mapping.get(novel_number - 1)

    def refresh_state(self) -> None:
        self.characters, self.aliases, self.voices = load_state(self.book_dir)

    def _character_for_name(self, name: str) -> Optional[str]:
        key = normalized_name(name)
        if not key:
            return None
        for alias, character_id in self.aliases.items():
            if normalized_name(alias) == key and character_id in self.characters:
                return character_id
        for character_id, record in self.characters.items():
            if normalized_name(record.get("name", "")) == key:
                return character_id
            if any(normalized_name(alias) == key for alias in record.get("aliases", [])):
                return character_id
        return None

    def _character_name(self, character_id: str) -> str:
        return str(self.characters.get(character_id, {}).get("name") or character_id)

    def _book_voice_profile_id(self, character_id: str) -> str:
        book_id = str(self.book.get("book_id") or self.book_dir.name).strip()
        return f"vp_{book_id}_{character_id}"

    def _voice_profile_id_for(self, voice_id: Optional[str]) -> Optional[str]:
        record = self.voices.get(str(voice_id or ""))
        if not isinstance(record, dict) or record.get("type") != "profile":
            return None
        value = str(record.get("voice_profile_id") or "").strip()
        return value or None

    def _remember_voice_sample(self, character_id: Optional[str], text: str) -> None:
        if not character_id or character_id not in self.characters:
            return
        voice_id = str(self.characters[character_id].get("voice_id") or "")
        voice = self.voices.get(voice_id)
        if not isinstance(voice, dict) or voice.get("type") != "profile":
            return
        if not str(voice.get("profile_sample_text") or "").strip():
            sample = re.sub(r"\s+", " ", str(text or "").strip())[:500].strip()
            if sample:
                voice["profile_sample_text"] = sample

    def _voice_design_description(self, character_id: str, voice_id: str) -> str:
        character = self.characters.get(character_id, {})
        voice = self.voices.get(voice_id, {})
        gender = str(character.get("gender") or "性别不明").strip()
        age = str(character.get("age") or "年龄不明").strip()
        style = str(voice.get("style") or character.get("description") or "自然、清晰、稳定").strip()
        return f"中文有声书角色声音；{gender}；{age}；{style}"

    def _ensure_voice_record(self, character_id: str, style: str = "") -> str:
        record = self.characters[character_id]
        voice_mode = os.environ.get("ALEXANDRIA_CHARACTER_VOICE_MODE", "profile").strip().lower()
        profile_mode = voice_mode in {"profile", "xc", "voice_profile", "design_profile"}
        existing = str(record.get("voice_id") or "")
        if existing and existing in self.voices:
            voice_record = self.voices[existing]
            if isinstance(voice_record, dict) and voice_record.get("voice_type") == "persistent":
                if profile_mode:
                    profile_id = str(
                        voice_record.get("voice_profile_id")
                        or voice_record.get("profile_voice_profile_id")
                        or self._book_voice_profile_id(character_id)
                    ).strip()
                    voice_record["voice_profile_id"] = profile_id
                    voice_record["voice_profile_backend"] = "xc"
                    voice_record["voice_profile_status"] = "pending"
                    voice_record["type"] = "profile"
                elif voice_mode in {"custom", "preset", "legacy"}:
                    if voice_record.get("type") == "profile":
                        voice_record["profile_voice_profile_id"] = (
                            str(voice_record.get("voice_profile_id") or "").strip()
                            or self._book_voice_profile_id(character_id)
                        )
                    voice_record["voice_profile_id"] = None
                    voice_record["voice_profile_status"] = "disabled_for_custom"
                    voice_record["type"] = "custom"
            return existing
        voice_id = _next_id("voice_", self.voices.keys())
        voice = _voice_choice(voice_id)
        voice_type = "profile" if profile_mode else ("design" if voice_mode == "design" else "custom")
        style = style or record.get("description") or "清晰、自然、稳定的说话声音"
        self.voices[voice_id] = {
            "voice_id": voice_id,
            "character_id": character_id,
            "voice_type": "persistent",
            "type": voice_type,
            "voice": voice,
            "style": style,
            "reference_audio": None,
            "ref_audio": None,
            "ref_text": None,
            "voice_profile_id": self._book_voice_profile_id(character_id) if profile_mode else None,
            "voice_profile_backend": "xc" if profile_mode else None,
            "voice_profile_status": "pending" if profile_mode else None,
            "profile_description": style,
            "profile_sample_text": None,
            "profile_seed": -1,
            "locked": True,
        }
        record["voice_id"] = voice_id
        return voice_id

    def _ensure_generic_voice(self, data: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], str]:
        data = data or {}
        voice_id = _generic_voice_id(data.get("gender", "male"), data.get("age", "middle"))
        if voice_id not in self.voices:
            voice, style = GENERIC_VOICE_CHOICES[voice_id]
            self.voices[voice_id] = {
                "voice_id": voice_id,
                "character_id": None,
                "voice_type": "generic",
                "type": "custom",
                "voice": voice,
                "style": style,
                "locked": True,
            }
        return None, voice_id

    def _new_character(
        self,
        name: str,
        data: Optional[Dict[str, Any]],
        chapter: int,
    ) -> Tuple[Optional[str], str]:
        data = data or {}
        name = str(name or "").strip()
        if _is_unnamed(name, data):
            return self._ensure_generic_voice(data)
        character_id = _next_id("char_", self.characters.keys())
        record: Dict[str, Any] = {
            "name": name,
            "aliases": [name],
            "gender": str(data.get("gender") or "unknown"),
            "age": str(data.get("age") or "unknown"),
            "description": str(data.get("voice_character") or data.get("description") or "").strip(),
            "first_seen": chapter,
            "last_seen": chapter,
            "voice_id": None,
        }
        self.characters[character_id] = record
        self.aliases[name] = character_id
        self._ensure_voice_record(character_id, record["description"])
        return character_id, record["voice_id"]

    def _ensure_character(
        self,
        name: str,
        data: Optional[Dict[str, Any]],
        chapter: int,
        supplied_id: Optional[str] = None,
    ) -> Tuple[Optional[str], str]:
        data = data or {}
        character_id = supplied_id if supplied_id in self.characters else self._character_for_name(name)
        if character_id:
            record = self.characters[character_id]
            display_name = str(name or record.get("name") or character_id).strip()
            if display_name and display_name not in record.setdefault("aliases", []):
                record["aliases"].append(display_name)
            if display_name:
                self.aliases.setdefault(display_name, character_id)
            record["last_seen"] = max(int(record.get("last_seen") or chapter), chapter)
            if not record.get("description") and data.get("voice_character"):
                record["description"] = str(data["voice_character"])
            voice_id = self._ensure_voice_record(character_id, str(data.get("voice_character") or ""))
            return character_id, voice_id
        return self._new_character(name, data, chapter)

    def _resolve_alias_target(self, value: str) -> Optional[str]:
        if value in self.characters:
            return value
        if value in self.aliases and self.aliases[value] in self.characters:
            return self.aliases[value]
        return self._character_for_name(value)

    def apply_analysis_metadata(
        self,
        chapter: int,
        result: Dict[str, Any],
        script_entries: List[Dict[str, Any]],
    ) -> None:
        """Merge Codex's small metadata payload into persistent state."""
        display_chapter = self.novel_chapter_number(chapter)
        new_by_name: Dict[str, Tuple[Optional[str], str]] = {}
        for item in result.get("new_characters", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            confidence = float(item.get("confidence", 1.0) or 0.0)
            if confidence < 0.5:
                continue
            cid, vid = self._ensure_character(name, item, display_chapter)
            new_by_name[normalized_name(name)] = (cid, vid)

        # High-confidence aliases are deliberately automatic; lower confidence
        # stays out of state so the user can add it explicitly with `character alias`.
        for item in result.get("possible_aliases", []) or []:
            if not isinstance(item, dict) or float(item.get("confidence", 0.0) or 0.0) <= 0.9:
                continue
            alias = str(item.get("name") or "").strip()
            target = self._resolve_alias_target(str(item.get("character_id") or ""))
            if not target and normalized_name(alias) in new_by_name:
                target = new_by_name[normalized_name(alias)][0]
            if alias and target:
                self.aliases[alias] = target
                if alias not in self.characters[target].setdefault("aliases", []):
                    self.characters[target]["aliases"].append(alias)

        # Script entries are an additional source of aliases and character
        # sightings.  This also repairs models that omit new_characters for a
        # named speaker.
        for entry in script_entries:
            if not isinstance(entry, dict):
                continue
            speaker = str(entry.get("speaker") or "").strip()
            if not speaker or normalized_name(speaker) in {"narrator", "旁白", "narration"}:
                continue
            supplied = str(entry.get("character_id") or "") or None
            data = new_by_name.get(normalized_name(speaker))
            if supplied and supplied in self.characters:
                cid, vid = self._ensure_character(speaker, {}, display_chapter, supplied_id=supplied)
            elif data:
                cid, vid = data
            else:
                # Known aliases resolve here; genuinely unknown speakers become
                # persistent characters only when they look named.
                cid, vid = self._ensure_character(speaker, {}, display_chapter)
            if cid:
                entry["character_id"] = cid
                entry["voice_id"] = vid
                entry["voice_profile_id"] = self._voice_profile_id_for(vid)
                self._remember_voice_sample(cid, str(entry.get("text") or ""))
            else:
                entry["character_id"] = None
                entry["voice_id"] = vid
                entry["voice_profile_id"] = None

        save_state(self.book_dir, self.characters, self.aliases, self.voices)

    def related_context(self, chapter: int, source: str) -> Dict[str, Any]:
        """Select a small roster using string matching, not embeddings."""
        seen: List[str] = []
        haystack = normalized_name(source)
        for alias, character_id in sorted(self.aliases.items(), key=lambda pair: len(pair[0]), reverse=True):
            if normalized_name(alias) and normalized_name(alias) in haystack and character_id not in seen:
                seen.append(character_id)
        # The previous novel chapter is useful even when this chapter starts
        # with a pronoun or a title.  Do not use internal source numbers here:
        # the imported manifest contains heading-only records between chapters.
        previous_internal = self._previous_internal_chapter(chapter)
        if previous_internal is not None:
            previous_script = chapter_root(self.book_dir, previous_internal) / "script.json"
            previous = read_json(previous_script, [])
            if isinstance(previous, list):
                for item in previous:
                    cid = item.get("character_id") if isinstance(item, dict) else None
                    if cid in self.characters and cid not in seen:
                        seen.append(cid)
        result = []
        for cid in seen[:30]:
            record = self.characters.get(cid, {})
            result.append({
                "character_id": cid,
                "name": record.get("name"),
                "aliases": record.get("aliases", []),
                "gender": record.get("gender"),
                "age": record.get("age"),
                "description": record.get("description", ""),
                "voice_id": record.get("voice_id"),
            })
        return {"characters": result, "aliases": {alias: self.aliases[alias] for alias in self.aliases if self.aliases[alias] in seen}}

    def _previous_context(self, chapter: int) -> Dict[str, Any]:
        previous_internal = self._previous_internal_chapter(chapter)
        if previous_internal is None:
            return {"summary": "", "tail": []}
        previous_dir = chapter_root(self.book_dir, previous_internal)
        summary = (previous_dir / "summary.txt").read_text(encoding="utf-8") if (previous_dir / "summary.txt").exists() else ""
        script = read_json(previous_dir / "script.json", [])
        tail = script[-10:] if isinstance(script, list) else []
        return {"summary": summary[:1200], "tail": tail}

    def _script_prompt(
        self,
        chapter: int,
        chunk_number: int,
        total_chunks: int,
        chunk: str,
        previous_entries: List[Dict[str, Any]],
    ) -> str:
        chapter_label = self.chapter_label(chapter)
        context = self.related_context(chapter, chunk)
        previous = self._previous_context(chapter)
        return f"""你是中文长篇有声书脚本分析器。只理解文本，不读写项目文件。

请把当前片段转成旁白/对白脚本，并同时识别新人物和高置信别名。
这是{chapter_label}的第 {chunk_number}/{total_chunks} 个片段。

硬性规则：
1. 必须返回符合 JSON Schema 的对象，不要 Markdown，不要解释。
2. script 必须覆盖当前片段的全部文字，不能改写、删节或重复；按自然段、对白边界拆分。
3. 旁白 speaker 固定为 NARRATOR，character_id 为 null。
4. 已知人物使用给出的 character_id；遇到新称呼先在 possible_aliases 中报告，不要凭空创建重复人物。
5. 每一段引号内的对白必须拆成独立脚本条目，speaker 必须是实际说话人；绝不能把人物对白连同引号塞进 NARRATOR。
6. 对白说话人即使只以“秃眉大汉、女修、韩立”等称呼出现，也必须单独标注；有名字的人必须进入 new_characters 或使用已知 character_id。
7. 无名路人/弟子/守卫等用 new_characters 的 named=false、gender、age 描述，Python 会分配按性别年龄区分的通用声音。
8. new_characters 只写当前确实新出现的人物，voice_character 只用简短的说话方式（如“沉稳、低沉、克制”），不要写文学评论。
9. emotion 只写简短值，如 neutral、calm、tense、angry、sad、excited、whisper；不确定就 neutral。

已知相关人物：
{json.dumps(context["characters"], ensure_ascii=False, indent=2)}

相关别名：
{json.dumps(context["aliases"], ensure_ascii=False, indent=2)}

上一章摘要：
{previous["summary"]}

上一章末尾脚本：
{json.dumps(previous["tail"], ensure_ascii=False)}

本片段前面已经确认的脚本末尾：
{json.dumps(previous_entries[-10:], ensure_ascii=False)}

当前片段：
{chunk}
"""

    def _summary_prompt(self, chapter: int, script: List[Dict[str, Any]]) -> str:
        chapter_label = self.chapter_label(chapter)
        previous = self._previous_context(chapter)
        return f"""你是中文长篇有声书的章节摘要器。只返回 JSON Schema 对象，不要 Markdown 或解释。
把{chapter_label}压缩成 300-800 个中文字符的摘要，保留人物行动、关键冲突、修炼/物品/地点等会影响下一章理解的信息，但不要添加原文没有的事实。
character_updates 只记录本章对已有人物长期说话方式/身份的补充，通常可以为空；不要创建关系图谱。

上一章摘要：
{previous["summary"]}

本章脚本：
{json.dumps(script, ensure_ascii=False)}
"""

    def _cache_path(self, chapter: int, kind: str, source_hash: str, version: str) -> Path:
        return chapter_root(self.book_dir, chapter) / f".{kind}_{source_hash[:16]}_{version}.json"

    @staticmethod
    def _invalidate_audio_files(chapter_dir: Path) -> None:
        lines_dir = chapter_dir / "lines"
        if lines_dir.exists():
            for path in lines_dir.glob("line_*.wav"):
                try:
                    path.unlink()
                except OSError:
                    pass
        for path in (
            chapter_dir / "audio.wav",
            chapter_dir / f"audio{CHAPTER_AUDIO_SUFFIX}",
            chapter_dir / f"audio{LEGACY_CHAPTER_AUDIO_SUFFIX}",
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _normalize_script_entries(
        self,
        result: Dict[str, Any],
        chapter: int,
        source_chunk: str,
    ) -> List[Dict[str, Any]]:
        chapter_label = self.chapter_label(chapter)
        novel_number = self.novel_chapter_number(chapter)
        raw_entries = result.get("script") or []
        if not isinstance(raw_entries, list):
            raise PipelineError(f"{chapter_label} Codex script 不是数组")
        entries: List[Dict[str, Any]] = []
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            line_text = str(raw.get("text") or "").strip()
            if not line_text:
                continue
            speaker = str(raw.get("speaker") or "NARRATOR").strip()
            if normalized_name(speaker) in {"narrator", "旁白", "narration", "叙述"}:
                speaker = "NARRATOR"
                character_id = None
                voice_id = "voice_narrator"
                voice_profile_id = None
            else:
                supplied_id = str(raw.get("character_id") or "") or None
                voice_id = ""
                character_id = supplied_id if supplied_id in self.characters else self._character_for_name(speaker)
                if character_id:
                    voice_id = self._ensure_voice_record(character_id)
                else:
                    character_id, voice_id = self._ensure_character(
                        speaker, {}, novel_number, supplied_id=supplied_id
                    )
                if not voice_id:
                    _, voice_id = self._ensure_generic_voice({})
                voice_profile_id = self._voice_profile_id_for(voice_id)
                self._remember_voice_sample(character_id, line_text)
            emotion = str(raw.get("emotion") or "neutral").strip() or "neutral"
            entries.append({
                "speaker": speaker,
                "character_id": character_id,
                "voice_id": voice_id,
                "voice_profile_id": voice_profile_id,
                "text": line_text,
                "emotion": emotion,
                "instruct": emotion,
            })
        if not entries and source_chunk.strip():
            raise PipelineError(f"{chapter_label} Codex 没有返回可用脚本条目")
        return entries

    @staticmethod
    def _source_has_dialogue(source: str) -> bool:
        quote_pairs = re.findall(r"[“「『\"](.*?)[”」』\"]", str(source or ""), flags=re.S)
        for body in quote_pairs:
            body = re.sub(r"\s+", "", body)
            if len(body) >= 8 or re.search(r"[。！？!?，：:；;]", body):
                return True
        return False

    def _validate_script_roles(
        self,
        chapter: int,
        source: str,
        script: List[Dict[str, Any]],
    ) -> None:
        chapter_label = self.chapter_label(chapter)
        non_narrator = [
            item for item in script
            if isinstance(item, dict)
            and normalized_name(str(item.get("speaker") or "")) not in {"", "narrator", "旁白", "narration", "叙述"}
        ]
        if self._source_has_dialogue(source) and not non_narrator:
            raise PipelineError(
                f"{chapter_label} 检测到原文对白，但脚本全部标成 NARRATOR；"
                "已停止，禁止用旁白声音代替角色对白，请重新分析"
            )

    def analyze_chapter(self, chapter: int, force: bool = False) -> Dict[str, Any]:
        chapter_label = self.chapter_label(chapter)
        chapter_dir = chapter_root(self.book_dir, chapter)
        source_path = chapter_dir / "source.txt"
        if not source_path.exists():
            raise PipelineError(f"{chapter_label}不存在：{source_path}")
        source = source_path.read_text(encoding="utf-8")
        source_hash = sha256_file(chapter_dir / "source.txt")
        status = load_chapter_status(self.book_dir, chapter)
        script_path = chapter_dir / "script.json"
        progress_path = chapter_dir / "analysis_progress.json"
        cache_path = self._cache_path(chapter, "analysis", source_hash, PROMPT_VERSION)

        if not status.get("analysis"):
            # The script is being created or replaced (for example after a
            # prompt-version change), so old line audio cannot be trusted.
            self._invalidate_audio_files(chapter_dir)

        if not force and status.get("analysis") and script_path.exists():
            return read_json(script_path, []) or []

        if force:
            for stale in (script_path, chapter_dir / "summary.txt", chapter_dir / "finalize.json", progress_path):
                try:
                    stale.unlink()
                except FileNotFoundError:
                    pass
            status.update({
                "analysis": False, "summary": False, "voices": False,
                "tts": False, "done": False, "analysis_chunks_done": 0,
                "tts_lines_done": 0,
            })
            self._invalidate_audio_files(chapter_dir)

        cached = None if force else read_json(cache_path, None)
        if isinstance(cached, dict) and cached.get("source_sha256") == source_hash and cached.get("prompt_version") == PROMPT_VERSION:
            script = cached.get("script") or []
            if script:
                self._validate_script_roles(chapter, source, script)
                atomic_write_json(script_path, script)
                status["analysis_chunks_done"] = len(cached.get("chunks") or [])
                status["analysis"] = True
                status["voices"] = True
                save_chapter_status(self.book_dir, chapter, status)
                self.refresh_state()
                return script

        max_chars = int(
            self.book.get("analysis_chunk_size")
            or os.environ.get("ALEXANDRIA_ANALYSIS_CHUNK_SIZE", "4000")
        )
        chunks = split_natural(source, max(500, max_chars))
        progress = read_json(progress_path, None) if not force else None
        if not isinstance(progress, dict) or progress.get("source_sha256") != source_hash or progress.get("prompt_version") != PROMPT_VERSION:
            progress = {"source_sha256": source_hash, "prompt_version": PROMPT_VERSION, "chunks": []}
        completed_chunks = progress.get("chunks") if isinstance(progress.get("chunks"), list) else []
        all_entries: List[Dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            if index < len(completed_chunks) and isinstance(completed_chunks[index], dict):
                cached_chunk = completed_chunks[index]
                if cached_chunk.get("text_hash") == sha256_text(chunk) and isinstance(cached_chunk.get("result"), dict):
                    result = cached_chunk["result"]
                else:
                    result = None
            else:
                result = None
            if result is None:
                prompt = self._script_prompt(chapter, index + 1, len(chunks), chunk, all_entries)
                result = self.codex.run(prompt, SCRIPT_SCHEMA)
                while len(completed_chunks) <= index:
                    completed_chunks.append({})
                completed_chunks[index] = {"text_hash": sha256_text(chunk), "result": result}
                progress["chunks"] = completed_chunks
                atomic_write_json(progress_path, progress)
            # Register explicitly reported new characters before normalizing
            # line speakers; otherwise an alias used in the same chunk could
            # briefly look like a second new character.
            self.apply_analysis_metadata(chapter, result, [])
            normalized = self._normalize_script_entries(result, chapter, chunk)
            self.apply_analysis_metadata(chapter, result, normalized)
            all_entries.extend(normalized)
            status["analysis_chunks_done"] = index + 1
            save_chapter_status(self.book_dir, chapter, status)
            print(f"{chapter_label}: analyzed chunk {index + 1}/{len(chunks)} ({len(normalized)} lines)")

        if not all_entries:
            raise PipelineError(f"{chapter_label}没有可保存的脚本")
        self._validate_script_roles(chapter, source, all_entries)
        # Ensure line IDs are deterministic and easy to inspect.
        for line_number, entry in enumerate(all_entries, 1):
            entry["line_id"] = line_number
        atomic_write_json(script_path, all_entries)
        cache_payload = {
            "source_sha256": source_hash,
            "prompt_version": PROMPT_VERSION,
            "created_at": now_iso(),
            "chunks": completed_chunks,
            "script": all_entries,
        }
        atomic_write_json(cache_path, cache_payload)
        status.update({"analysis": True, "voices": True, "tts": False, "done": False})
        save_chapter_status(self.book_dir, chapter, status)
        return all_entries

    def finalize_chapter(self, chapter: int, force: bool = False) -> str:
        chapter_label = self.chapter_label(chapter)
        chapter_dir = chapter_root(self.book_dir, chapter)
        script = read_json(chapter_dir / "script.json", [])
        if not isinstance(script, list) or not script:
            raise PipelineError(f"{chapter_label}没有 script.json，无法生成摘要")
        status = load_chapter_status(self.book_dir, chapter)
        source_hash = status.get("source_sha256") or sha256_file(chapter_dir / "source.txt")
        summary_path = chapter_dir / "summary.txt"
        cache_path = self._cache_path(chapter, "finalize", source_hash, SUMMARY_PROMPT_VERSION)
        if not force and status.get("summary") and summary_path.exists():
            return summary_path.read_text(encoding="utf-8")
        cached = None if force else read_json(cache_path, None)
        if isinstance(cached, dict) and cached.get("source_sha256") == source_hash:
            result = cached
        else:
            result = self.codex.run(self._summary_prompt(chapter, script), SUMMARY_SCHEMA)
            result = {
                "source_sha256": source_hash,
                "summary": str(result.get("summary") or "").strip(),
                "character_updates": result.get("character_updates") or [],
                "prompt_version": SUMMARY_PROMPT_VERSION,
            }
            atomic_write_json(cache_path, result)
        summary = str(result.get("summary") or "").strip()
        if not summary:
            if os.environ.get("ALEXANDRIA_FAKE_CODEX_RESPONSE") or os.environ.get("ALEXANDRIA_ALLOW_LOCAL_SUMMARY") == "1":
                # Development fallback only; production runs should receive
                # the structured Chapter Finalize response from Codex.
                summary = " ".join(str(item.get("text") or "") for item in script if isinstance(item, dict))[:800]
            else:
                raise PipelineError(f"{chapter_label} Codex 没有返回摘要")
        summary_path.write_text(summary + "\n", encoding="utf-8")
        for update in result.get("character_updates", []) or []:
            if not isinstance(update, dict):
                continue
            cid = self._resolve_alias_target(str(update.get("character_id") or ""))
            addition = str(update.get("description_append") or "").strip()
            if cid and addition:
                old = str(self.characters[cid].get("description") or "").strip()
                if addition not in old:
                    self.characters[cid]["description"] = f"{old}；{addition}".strip("；")
        save_state(self.book_dir, self.characters, self.aliases, self.voices)
        status["summary"] = True
        save_chapter_status(self.book_dir, chapter, status)
        return summary

    def analyze_and_finalize(self, chapter: int, force: bool = False) -> List[Dict[str, Any]]:
        script = self.analyze_chapter(chapter, force=force)
        self.finalize_chapter(chapter, force=force)
        return script

    def ensure_all_voice_ids(self, chapter: int) -> None:
        chapter_label = self.chapter_label(chapter)
        self.refresh_state()
        script_path = chapter_root(self.book_dir, chapter) / "script.json"
        script = read_json(script_path, [])
        if not isinstance(script, list):
            raise PipelineError(f"{chapter_label} script.json 格式错误")
        changed = False
        for entry in script:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("character_id")
            if cid in self.characters:
                voice_id = self._ensure_voice_record(cid)
                self._remember_voice_sample(cid, str(entry.get("text") or ""))
            elif entry.get("speaker") == "NARRATOR":
                voice_id = "voice_narrator"
            else:
                voice_id = entry.get("voice_id") or self._ensure_generic_voice({})[1]
            profile_id = self._voice_profile_id_for(voice_id)
            if entry.get("voice_id") != voice_id:
                entry["voice_id"] = voice_id
                changed = True
            if entry.get("voice_profile_id") != profile_id:
                entry["voice_profile_id"] = profile_id
                changed = True
        if changed:
            atomic_write_json(script_path, script)
        save_state(self.book_dir, self.characters, self.aliases, self.voices)
        status = load_chapter_status(self.book_dir, chapter)
        status["voices"] = True
        save_chapter_status(self.book_dir, chapter, status)

    def _tts_voice_config(self) -> Dict[str, Dict[str, Any]]:
        config: Dict[str, Dict[str, Any]] = {}
        for voice_id, record in self.voices.items():
            if not isinstance(record, dict):
                continue
            item = dict(record)
            item.setdefault("type", "custom")
            item.setdefault("voice", "Ryan")
            item.setdefault("default_style", item.get("style", ""))
            item.setdefault("character_style", item.get("style", ""))
            config[voice_id] = item
        return config

    def _voice_profile_for_entry(
        self,
        entry: Dict[str, Any],
        voice_config: Dict[str, Dict[str, Any]],
        line_number: Optional[int] = None,
    ) -> Optional[str]:
        """Select a per-emotion reference profile, falling back to the default."""
        voice_id = str(entry.get("voice_id") or "voice_narrator")
        voice_data = voice_config.get(voice_id, {})
        default_profile = str(voice_data.get("voice_profile_id") or "").strip() or None
        mapping = voice_data.get("voice_profile_by_emotion")
        if not isinstance(mapping, dict):
            return default_profile

        emotion = str(entry.get("emotion") or entry.get("instruct") or "neutral").strip().lower()
        candidates_value = mapping.get(emotion)
        if candidates_value is None:
            aliases = {
                "neutral": ["calm"],
                "calm": ["neutral"],
                "fear": ["afraid"],
                "tense": ["worried", "afraid"],
                "concern": ["worried"],
                "angry": ["annoyed", "pretend_fierce"],
                "excited": ["lively", "cheerful"],
                "happy": ["cheerful", "relieved_cheerful"],
                "sad": ["sorrow"],
                "confused": ["slightly_puzzled"],
                "confident": ["earnest", "smug"],
            }
            for alias in aliases.get(emotion, []):
                if alias in mapping:
                    candidates_value = mapping[alias]
                    break
        if candidates_value is None:
            candidates_value = mapping.get("default")
        if isinstance(candidates_value, str):
            candidates = [candidates_value]
        elif isinstance(candidates_value, list):
            candidates = [str(value).strip() for value in candidates_value if str(value).strip()]
        else:
            candidates = []
        if not candidates:
            return default_profile
        try:
            position = int(line_number if line_number is not None else entry.get("line_id") or 1)
        except (TypeError, ValueError):
            position = 1
        return candidates[(max(position, 1) - 1) % len(candidates)]
    def _load_tts_engine(self) -> Any:
        configured_mode = load_config().get("tts", {}).get("mode")
        if os.environ.get("ALEXANDRIA_TTS_MODE", "").lower() == "fake" or configured_mode == "fake":
            return _FakeTTSEngine()
        sys.path.insert(0, str(APP_DIR))
        try:
            from tts import TTSEngine  # type: ignore
        except Exception as exc:
            raise PipelineError(f"无法加载 Alexandria TTS 后端：{exc}") from exc
        config = load_config()
        try:
            return TTSEngine(config)
        except Exception as exc:
            raise PipelineError(f"无法初始化 TTS 引擎：{exc}") from exc

    @staticmethod
    def _emotion_instruction(emotion: str) -> str:
        value = str(emotion or "neutral").strip().lower()
        mapping = {
            "neutral": "neutral",
            "calm": "calm, restrained",
            "tense": "tense, urgent",
            "angry": "angry, forceful",
            "sad": "sad, subdued",
            "excited": "excited, energetic",
            "whisper": "quiet, intimate whisper",
            "fear": "nervous, fearful",
            "happy": "warm, cheerful",
        }
        return mapping.get(value, value or "neutral")

    def _render_line(self, engine: Any, entry: Dict[str, Any], output_path: Path) -> None:
        voice_id = str(entry.get("voice_id") or "voice_narrator")
        voice_config = self._tts_voice_config()
        if voice_id not in voice_config:
            raise PipelineError(f"找不到声音配置：{voice_id}")
        selected_profile = self._voice_profile_for_entry(entry, voice_config)
        if selected_profile:
            voice_config = dict(voice_config)
            selected_voice_data = dict(voice_config[voice_id])
            selected_voice_data["voice_profile_id"] = selected_profile
            voice_config[voice_id] = selected_voice_data
        output_path.parent.mkdir(parents=True, exist_ok=True)
        success = engine.generate_voice(
            str(entry.get("text") or ""),
            self._emotion_instruction(str(entry.get("emotion") or entry.get("instruct") or "neutral")),
            voice_id,
            voice_config,
            str(output_path),
        )
        if not success or not output_path.exists() or output_path.stat().st_size == 0:
            raise PipelineError(f"TTS 生成失败：line {entry.get('line_id') or '?'} / {voice_id}")

    def _materialize_design_voice(self, engine: Any, entry: Dict[str, Any]) -> None:
        """Ensure one persistent xc VoiceDesign profile exists for a named role."""
        voice_id = str(entry.get("voice_id") or "")
        record = self.voices.get(voice_id)
        if not isinstance(record, dict):
            return

        if record.get("type") == "profile":
            profile_id = str(record.get("voice_profile_id") or "").strip()
            if not profile_id:
                raise PipelineError(f"声音 {voice_id} 缺少 voice_profile_id")
            if record.get("voice_profile_status") == "ready":
                return
            sample = str(record.get("profile_sample_text") or entry.get("text") or "").strip()[:500]
            if not sample:
                raise PipelineError(f"角色声音 {profile_id} 没有可用于 VoiceDesign 的样本文本")
            description = self._voice_design_description(
                str(record.get("character_id") or ""), voice_id
            )
            if not hasattr(engine, "ensure_voice_profile"):
                raise PipelineError(
                    f"xc TTS 不支持 VoiceDesign profile（需要 /voice_profiles/design）：{profile_id}"
                )
            try:
                response = engine.ensure_voice_profile(
                    profile_id,
                    description,
                    sample,
                    language=load_config().get("tts", {}).get("language", "Chinese"),
                    seed=int(record.get("profile_seed", -1)),
                )
            except Exception as exc:
                record["voice_profile_status"] = "failed"
                record["voice_profile_error"] = str(exc)
                save_state(self.book_dir, self.characters, self.aliases, self.voices)
                raise PipelineError(f"VoiceDesign 生成 {profile_id} 失败：{exc}") from exc
            record.update({
                "voice_profile_status": "ready",
                "voice_profile_backend": "xc",
                "voice_profile_id": str(response.get("voice_profile_id") or profile_id),
                "profile_description": description,
                "profile_sample_text": sample,
                "profile_ready_at": now_iso(),
                "voice_profile_error": None,
            })
            save_state(self.book_dir, self.characters, self.aliases, self.voices)
            return

        # Keep the old local-only design mode available for explicit legacy use.
        if record.get("type") != "design" or record.get("reference_audio"):
            return
        if getattr(engine, "mode", "local") != "local" or not hasattr(engine, "generate_voice_design"):
            raise PipelineError(
                f"声音 {voice_id} 仍是旧 design 配置；外部 xc 必须使用 type=profile 并注册 VoiceDesign"
            )
        sample = str(entry.get("text") or "").strip()
        if not sample:
            return
        description = str(record.get("style") or "clear, natural speaking voice")
        try:
            generated_path, _ = engine.generate_voice_design(description=description, sample_text=sample)
        except Exception as exc:
            raise PipelineError(f"VoiceDesign 生成 {voice_id} 失败：{exc}") from exc
        reference_dir = self.book_dir / "state" / "voice_refs"
        reference_dir.mkdir(parents=True, exist_ok=True)
        reference_path = reference_dir / f"{voice_id}.wav"
        shutil.copy2(generated_path, reference_path)
        try:
            relative_reference = reference_path.relative_to(ROOT_DIR)
            tts_reference = str(relative_reference)
        except ValueError:
            tts_reference = str(reference_path)
        record.update({
            "type": "clone",
            "reference_audio": tts_reference,
            "ref_audio": tts_reference,
            "ref_text": sample,
            "generated_once": True,
        })
        save_state(self.book_dir, self.characters, self.aliases, self.voices)

    def _ensure_render_profiles(self, engine: Any, script: List[Dict[str, Any]]) -> None:
        """Register every named profile before rendering any line audio."""
        seen = set()
        for entry in script:
            if not isinstance(entry, dict):
                continue
            voice_id = str(entry.get("voice_id") or "")
            if voice_id in seen:
                continue
            record = self.voices.get(voice_id)
            if isinstance(record, dict) and record.get("type") == "profile":
                seen.add(voice_id)
                self._materialize_design_voice(engine, entry)

    def _combine_chapter_audio(self, chapter: int, script: List[Dict[str, Any]], line_paths: List[Path]) -> Path:
        chapter_label = self.chapter_label(chapter)
        # Alexandria normally emits WAV files.  Use the standard library for
        # the merge so the CLI does not require pydub merely to checkpoint a
        # chapter; ffmpeg is still used for the final M4B container with AAC audio.
        for path in line_paths:
            if not path.exists():
                raise PipelineError(f"缺少音频行：{path}")
        speakers = [str(entry.get("voice_id") or "voice_narrator") for entry in script]
        pauses = [entry.get("pause_after") for entry in script]
        config = load_config().get("tts", {})
        pause_ms = int(config.get("pause_between_speakers_ms", 500))
        same_pause_ms = int(config.get("pause_same_speaker_ms", 250))
        wav_path = chapter_root(self.book_dir, chapter) / "audio.wav"
        self._merge_wav_files(line_paths, speakers, pauses, pause_ms, same_pause_ms, wav_path)
        m4b_path = chapter_root(self.book_dir, chapter) / f"audio{CHAPTER_AUDIO_SUFFIX}"
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise PipelineError("导出 m4b 需要 ffmpeg，请安装 ffmpeg 后重试")
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(wav_path), "-c:a", "aac", "-b:a", "128k", "-vn", str(m4b_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not m4b_path.exists() or m4b_path.stat().st_size == 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise PipelineError(f"ffmpeg 导出{chapter_label} M4B 失败：{detail[-800:]}")
        return m4b_path

    @staticmethod
    def _merge_wav_files(
        line_paths: List[Path],
        speakers: List[str],
        pauses: List[Any],
        pause_ms: int,
        same_pause_ms: int,
        output_path: Path,
    ) -> None:
        if not line_paths:
            raise PipelineError("没有可合并的音频行")
        try:
            with wave.open(str(line_paths[0]), "rb") as first:
                params = first.getparams()
                first_frames = first.readframes(first.getnframes())
        except (wave.Error, OSError) as exc:
            raise PipelineError(f"音频行必须是 WAV（{line_paths[0]}：{exc}）") from exc
        frame_width = params.nchannels * params.sampwidth
        chunks = [first_frames]
        previous_speaker = speakers[0] if speakers else ""
        for index, path in enumerate(line_paths[1:], 1):
            gap = pauses[index - 1] if index - 1 < len(pauses) else None
            if gap is None:
                gap = same_pause_ms if speakers[index] == previous_speaker else pause_ms
            frames_of_silence = int(max(0, int(gap)) * params.framerate / 1000)
            chunks.append(b"\x00" * frames_of_silence * frame_width)
            try:
                with wave.open(str(path), "rb") as current:
                    if (
                        current.getnchannels() != params.nchannels
                        or current.getsampwidth() != params.sampwidth
                        or current.getframerate() != params.framerate
                        or current.getcomptype() != params.comptype
                    ):
                        raise PipelineError(f"音频行参数不一致：{path}")
                    chunks.append(current.readframes(current.getnframes()))
            except (wave.Error, OSError) as exc:
                raise PipelineError(f"无法读取音频行 {path}: {exc}") from exc
            previous_speaker = speakers[index] if index < len(speakers) else previous_speaker
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as output:
            output.setparams(params)
            output.writeframes(b"".join(chunks))

    @staticmethod
    def _convert_audio_to_m4b(source_path: Path, target_path: Path) -> Path:
        """Convert or copy one chapter into the default M4B container atomically."""
        if not source_path.exists():
            raise PipelineError(f"音频源不存在：{source_path}")
        if source_path.resolve() == target_path.resolve():
            return target_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_path.with_name(
            f".{target_path.stem}.{os.getpid()}.tmp{CHAPTER_AUDIO_SUFFIX}"
        )
        try:
            if source_path.suffix.lower() == CHAPTER_AUDIO_SUFFIX:
                shutil.copy2(source_path, temporary)
                os.replace(temporary, target_path)
                return target_path

            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise PipelineError("M4A 转 M4B 需要 ffmpeg，请安装 ffmpeg 后重试")
            failures: List[str] = []
            for codec_args in (("-c:a", "copy"), ("-c:a", "aac", "-b:a", "128k")):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                result = subprocess.run(
                    [
                        ffmpeg, "-y", "-i", str(source_path),
                        "-map", "0:a:0", "-map_metadata", "0", "-vn",
                        *codec_args, "-movflags", "+faststart", str(temporary),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0 and temporary.exists() and temporary.stat().st_size > 0:
                    os.replace(temporary, target_path)
                    return target_path
                failures.append((result.stderr or result.stdout or "").strip()[-400:])
            detail = next((item for item in reversed(failures) if item), "unknown ffmpeg error")
            raise PipelineError(f"M4A 转 M4B 失败：{detail}")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _publish_chapter_audio(self, chapter: int, source_path: Path) -> Path:
        """Publish one finished chapter atomically for Audiobookshelf."""
        if not source_path.exists():
            raise PipelineError(f"音频源不存在：{source_path}")
        output_chapters = self.book_dir / "output" / "chapters"
        output_chapters.mkdir(parents=True, exist_ok=True)
        arc = self.chapter_arc(chapter)
        novel_number = self.novel_chapter_number(chapter)
        published = output_chapters / chapter_audio_filename(
            self.book_dir, self.book, chapter, arc=arc, novel_number=novel_number
        )

        # Convert first, then remove historical names so a failed conversion
        # never destroys the only published copy.
        self._convert_audio_to_m4b(source_path, published)
        legacy_names = {
            f"chapter_{chapter:06d}{LEGACY_CHAPTER_AUDIO_SUFFIX}",
            f"chapter_{chapter:06d}{CHAPTER_AUDIO_SUFFIX}",
        }
        if published.name.startswith(("正_", "仙_", "外_")):
            legacy_stem = "chapter_" + published.stem.split("_", 1)[1]
            legacy_names.update({
                published.stem + LEGACY_CHAPTER_AUDIO_SUFFIX,
                legacy_stem + LEGACY_CHAPTER_AUDIO_SUFFIX,
                legacy_stem + CHAPTER_AUDIO_SUFFIX,
            })
        for legacy_name in legacy_names:
            legacy = output_chapters / legacy_name
            if legacy != published and legacy.exists():
                legacy.unlink()
        return published

    def render_chapter(self, chapter: int, force: bool = False, dry_run: bool = False) -> Path:
        chapter_label = self.chapter_label(chapter)
        chapter_dir = chapter_root(self.book_dir, chapter)
        script_path = chapter_dir / "script.json"
        script = read_json(script_path, [])
        if not isinstance(script, list) or not script:
            raise PipelineError(f"{chapter_label}没有 script.json，请先 analyze")
        source_text = (chapter_dir / "source.txt").read_text(encoding="utf-8")
        self._validate_script_roles(chapter, source_text, script)
        status = load_chapter_status(self.book_dir, chapter)
        m4b_path = chapter_dir / f"audio{CHAPTER_AUDIO_SUFFIX}"
        legacy_m4a_path = chapter_dir / f"audio{LEGACY_CHAPTER_AUDIO_SUFFIX}"
        if not force and status.get("tts"):
            if m4b_path.exists():
                self._publish_chapter_audio(chapter, m4b_path)
                return m4b_path
            if legacy_m4a_path.exists():
                self._convert_audio_to_m4b(legacy_m4a_path, m4b_path)
                legacy_m4a_path.unlink()
                self._publish_chapter_audio(chapter, m4b_path)
                return m4b_path
        self.ensure_all_voice_ids(chapter)
        # ensure_all_voice_ids may have refreshed state and rewritten script.
        script = read_json(script_path, [])
        line_dir = chapter_dir / "lines"
        line_dir.mkdir(exist_ok=True)
        if force:
            for path in line_dir.glob("line_*.wav"):
                try:
                    path.unlink()
                except OSError:
                    pass
            for path in (chapter_dir / "audio.wav", m4b_path, legacy_m4a_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            status["tts_lines_done"] = 0
            status["tts"] = False
            status["done"] = False

        engine = None if dry_run else self._load_tts_engine()
        if engine is not None:
            self._ensure_render_profiles(engine, script)
        line_paths: List[Path] = []
        pending: List[Tuple[int, Dict[str, Any], Path]] = []
        for index, entry in enumerate(script, 1):
            line_path = line_dir / f"line_{index:06d}.wav"
            line_paths.append(line_path)
            if line_path.exists() and line_path.stat().st_size > 0 and not force:
                status["tts_lines_done"] = index
                save_chapter_status(self.book_dir, chapter, status)
                continue
            if dry_run:
                # Dry-run is intended for validating state transitions and
                # prompts on machines without a GPU.  It deliberately does not
                # claim TTS completion or create a fake audiobook.
                print(f"{chapter_label}: would render line {index}/{len(script)}")
                continue
            self._materialize_design_voice(engine, entry)
            pending.append((index, entry, line_path))

        if dry_run:
            return m4b_path

        if (
            getattr(engine, "supports_http_batch", False)
            and hasattr(engine, "generate_batch")
            and pending
        ):
            voice_config = self._tts_voice_config()
            batch_chunks: List[Dict[str, Any]] = []
            for index, entry, line_path in pending:
                voice_id = str(entry.get("voice_id") or "voice_narrator")
                if voice_id not in voice_config:
                    raise PipelineError(f"Missing voice configuration: {voice_id}")
                temp_path = line_dir / f"temp_batch_{index}.wav"
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                batch_chunks.append({
                    "index": index,
                    "text": str(entry.get("text") or ""),
                    "instruct": self._emotion_instruction(
                        str(entry.get("emotion") or entry.get("instruct") or "neutral")
                    ),
                    "speaker": voice_id,
                    "emotion": str(entry.get("emotion") or entry.get("instruct") or "neutral"),
                    "voice_profile_id": self._voice_profile_for_entry(entry, voice_config, index),
                })

            print(
                f"{chapter_label}: rendering {len(batch_chunks)} lines via "
                "native HTTP TTS batches"
            )
            batch_result = engine.generate_batch(
                batch_chunks,
                voice_config,
                str(line_dir),
                -1,
            )
            completed_ids = {
                int(index) for index in batch_result.get("completed", [])
            }
            failure_map = {
                int(index): str(error)
                for index, error in batch_result.get("failed", [])
            }
            missing = []
            for index, entry, line_path in pending:
                temp_path = line_dir / f"temp_batch_{index}.wav"
                if index in completed_ids and temp_path.exists() and temp_path.stat().st_size > 0:
                    temp_path.replace(line_path)
                    print(f"{chapter_label}: rendered line {index}/{len(script)}")
                else:
                    missing.append((index, failure_map.get(index, "missing output")))

            contiguous = 0
            while contiguous < len(line_paths):
                candidate = line_paths[contiguous]
                if not candidate.exists() or candidate.stat().st_size <= 0:
                    break
                contiguous += 1
            status["tts_lines_done"] = contiguous
            save_chapter_status(self.book_dir, chapter, status)
            if missing:
                detail = "; ".join(
                    f"line {index}: {message}" for index, message in missing
                )
                raise PipelineError(f"HTTP TTS batch generation failed: {detail}")
        else:
            configured_workers = 2
            try:
                configured_workers = max(1, int(load_config().get("tts", {}).get("parallel_workers", 2)))
            except (TypeError, ValueError):
                configured_workers = 2
            endpoint_count = max(1, int(getattr(engine, "endpoint_count", 1)))
            if getattr(engine, "uses_http_tts", False):
                worker_count = min(configured_workers, endpoint_count)
            else:
                worker_count = 1

            if worker_count <= 1 or len(pending) <= 1:
                for index, entry, line_path in pending:
                    self._render_line(engine, entry, line_path)
                    status["tts_lines_done"] = index
                    save_chapter_status(self.book_dir, chapter, status)
                    print(f"{chapter_label}: rendered line {index}/{len(script)}")
            else:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                print(
                    f"{chapter_label}: rendering {len(pending)} pending lines "
                    f"with {worker_count} HTTP TTS workers"
                )

                def render_pending(item: Tuple[int, Dict[str, Any], Path]) -> int:
                    index, entry, line_path = item
                    self._render_line(engine, entry, line_path)
                    return index

                failures: List[Tuple[int, Exception]] = []
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = {
                        executor.submit(render_pending, item): item[0]
                        for item in pending
                    }
                    for future in as_completed(futures):
                        index = futures[future]
                        try:
                            future.result()
                            print(f"{chapter_label}: rendered line {index}/{len(script)}")
                        except Exception as exc:
                            failures.append((index, exc))
                            print(f"{chapter_label}: line {index} failed: {exc}")
                        contiguous = 0
                        while contiguous < len(line_paths):
                            candidate = line_paths[contiguous]
                            if not candidate.exists() or candidate.stat().st_size <= 0:
                                break
                            contiguous += 1
                        status["tts_lines_done"] = contiguous
                        save_chapter_status(self.book_dir, chapter, status)

                if failures:
                    index, exc = sorted(failures, key=lambda item: item[0])[0]
                    raise PipelineError(f"Parallel TTS generation failed: line {index}: {exc}")
        self._combine_chapter_audio(chapter, script, line_paths)
        self._publish_chapter_audio(chapter, m4b_path)
        status.update({"voices": True, "tts": True, "done": True, "tts_lines_done": len(script)})
        save_chapter_status(self.book_dir, chapter, status)
        return m4b_path

    def review_chapter(self, chapter: int, force: bool = False) -> List[Dict[str, Any]]:
        """Manually review an existing chapter; never run as part of `run`."""
        chapter_label = self.chapter_label(chapter)
        chapter_dir = chapter_root(self.book_dir, chapter)
        source = (chapter_dir / "source.txt").read_text(encoding="utf-8")
        script = read_json(chapter_dir / "script.json", [])
        if not isinstance(script, list) or not script:
            raise PipelineError(f"{chapter_label}没有可审校的脚本")
        source_hash = sha256_file(chapter_dir / "source.txt")
        review_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["script"],
            "properties": {
                "script": {"type": "array", "items": SCRIPT_SCHEMA["properties"]["script"]["items"]}
            },
        }
        prompt = f"""你是中文有声书脚本审校器。只返回 JSON，不要解释。
保持每个 text 的原文内容，不增删文字；只修正明显的旁白/对白归属、speaker 和 emotion。
已有持久人物身份不能重建，保留已有 character_id、voice_id；每一段对白都必须有实际说话人，不能把对白放在 NARRATOR 中。
输出完整脚本数组。
原始章节：\n{source}\n\n当前脚本：\n{json.dumps(script, ensure_ascii=False)}"""
        result = self.codex.run(prompt, review_schema)
        reviewed = result.get("script") if isinstance(result.get("script"), list) else None
        if not reviewed:
            raise PipelineError("Codex 审校没有返回脚本")
        normalized: List[Dict[str, Any]] = []
        novel_number = self.novel_chapter_number(chapter)
        for raw in reviewed:
            if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
                continue
            old = next((item for item in script if item.get("text") == raw.get("text")), {})
            speaker = str(raw.get("speaker") or old.get("speaker") or "NARRATOR").strip()
            entry = dict(old)
            entry.update({
                "speaker": speaker,
                "text": str(raw.get("text") or "").strip(),
                "emotion": str(raw.get("emotion") or old.get("emotion") or "neutral"),
            })
            if normalized_name(speaker) in {"narrator", "旁白", "narration", "叙述"}:
                entry["speaker"] = "NARRATOR"
                entry["character_id"] = None
                entry["voice_id"] = "voice_narrator"
                entry["voice_profile_id"] = None
            else:
                cid = str(entry.get("character_id") or "") or self._character_for_name(speaker)
                if cid not in self.characters:
                    cid, voice_id = self._ensure_character(speaker, {}, novel_number)
                else:
                    voice_id = self._ensure_voice_record(cid)
                entry["character_id"] = cid
                entry["voice_id"] = voice_id
                entry["voice_profile_id"] = self._voice_profile_id_for(voice_id)
                self._remember_voice_sample(cid, entry["text"])
            entry["instruct"] = entry["emotion"]
            normalized.append(entry)
        self._validate_script_roles(chapter, source, normalized)
        for index, entry in enumerate(normalized, 1):
            entry["line_id"] = index
        atomic_write_json(chapter_dir / "script.json", normalized)
        status = load_chapter_status(self.book_dir, chapter)
        status.update({"source_sha256": source_hash, "tts": False, "done": False, "tts_lines_done": 0})
        self._invalidate_audio_files(chapter_dir)
        save_state(self.book_dir, self.characters, self.aliases, self.voices)
        save_chapter_status(self.book_dir, chapter, status)
        return normalized

    def character_list(self) -> List[Tuple[str, Dict[str, Any]]]:
        return sorted(self.characters.items(), key=lambda item: item[0])

    def add_alias(self, character_id: str, alias: str) -> None:
        self.refresh_state()
        if character_id not in self.characters:
            raise PipelineError(f"人物不存在：{character_id}")
        alias = str(alias or "").strip()
        if not alias:
            raise PipelineError("alias 不能为空")
        existing = self._character_for_name(alias)
        if existing and existing != character_id:
            raise PipelineError(f"alias {alias!r} 已属于 {existing}，请先 merge")
        self.aliases[alias] = character_id
        aliases = self.characters[character_id].setdefault("aliases", [])
        if alias not in aliases:
            aliases.append(alias)
        save_state(self.book_dir, self.characters, self.aliases, self.voices)

    def merge_characters(self, source_id: str, target_id: str) -> None:
        """Merge SOURCE into TARGET and rewire all chapter scripts."""
        self.refresh_state()
        if source_id not in self.characters or target_id not in self.characters:
            raise PipelineError("merge 的两个参数都必须是有效的 char_ ID")
        if source_id == target_id:
            raise PipelineError("不能把人物合并到自己")
        source = self.characters[source_id]
        target = self.characters[target_id]
        for alias in [source.get("name"), *source.get("aliases", [])]:
            if alias and alias not in target.setdefault("aliases", []):
                target["aliases"].append(alias)
            if alias:
                self.aliases[str(alias)] = target_id
        target["first_seen"] = min(int(target.get("first_seen") or 1), int(source.get("first_seen") or 1))
        target["last_seen"] = max(int(target.get("last_seen") or 1), int(source.get("last_seen") or 1))
        if not target.get("description") and source.get("description"):
            target["description"] = source["description"]
        for alias, value in list(self.aliases.items()):
            if value == source_id:
                self.aliases[alias] = target_id
        source_voice = source.get("voice_id")
        target_voice = target.get("voice_id") or self._ensure_voice_record(target_id)
        for chapter_info in self.book.get("chapters", []):
            number = int(chapter_info.get("number", 0)) if isinstance(chapter_info, dict) else 0
            if not number:
                continue
            script_path = chapter_root(self.book_dir, number) / "script.json"
            script = read_json(script_path, None)
            if not isinstance(script, list):
                continue
            changed = False
            for entry in script:
                if not isinstance(entry, dict):
                    continue
                if entry.get("character_id") == source_id:
                    entry["character_id"] = target_id
                    entry["voice_id"] = target_voice
                    entry["voice_profile_id"] = self._voice_profile_id_for(target_voice)
                    if entry.get("speaker") == source.get("name"):
                        entry["speaker"] = target.get("name")
                    changed = True
                elif source_voice and entry.get("voice_id") == source_voice:
                    entry["voice_id"] = target_voice
                    entry["voice_profile_id"] = self._voice_profile_id_for(target_voice)
                    changed = True
            if changed:
                atomic_write_json(script_path, script)
                status = load_chapter_status(self.book_dir, number)
                status.update({"tts": False, "done": False, "tts_lines_done": 0})
                save_chapter_status(self.book_dir, number, status)
                self._invalidate_audio_files(chapter_root(self.book_dir, number))
        self.characters.pop(source_id, None)
        if source_voice and source_voice != target_voice:
            self.voices.pop(source_voice, None)
        save_state(self.book_dir, self.characters, self.aliases, self.voices)

    def export_m4b(
        self,
        first: Optional[int] = None,
        last: Optional[int] = None,
        arc: str = "main",
    ) -> Path:
        arc = normalize_arc(arc)
        mapping = self.chapter_maps.get(arc)
        if not mapping:
            raise PipelineError(f"没有识别出{arc_display_name(arc)}正文")
        all_numbers = sorted(mapping)
        first = min(all_numbers) if first is None else first
        last = max(all_numbers) if last is None else last
        if first <= 0 or last < first:
            raise PipelineError(f"{arc_display_name(arc)}章节导出范围无效")
        numbers = list(range(first, last + 1))
        missing = [number for number in numbers if number not in mapping]
        if missing:
            raise PipelineError(f"{arc_display_name(arc)}章节不存在，无法导出：{missing[:12]}")
        chapter_paths: List[Tuple[int, Path]] = []
        output_chapters = self.book_dir / "output" / "chapters"
        output_chapters.mkdir(parents=True, exist_ok=True)
        for novel_number in numbers:
            internal_number = mapping[novel_number]
            path = chapter_root(self.book_dir, internal_number) / f"audio{CHAPTER_AUDIO_SUFFIX}"
            if not path.exists():
                legacy_path = chapter_root(self.book_dir, internal_number) / f"audio{LEGACY_CHAPTER_AUDIO_SUFFIX}"
                if legacy_path.exists():
                    self._convert_audio_to_m4b(legacy_path, path)
                    legacy_path.unlink()
            if not path.exists():
                raise PipelineError(
                    f"{chapter_display_label(arc, novel_number)}缺少 audio.m4b，请先 render"
                )
            copied = self._publish_chapter_audio(internal_number, path)
            chapter_paths.append((novel_number, copied))
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise PipelineError("导出 m4b 需要 ffmpeg，请安装 ffmpeg 后重试")
        cache_stem = f"export_{arc}_{first}_{last}"
        concat_list = self.book_dir / "cache" / f"{cache_stem}.txt"
        meta_path = self.book_dir / "cache" / f"{cache_stem}.ffmeta"
        durations: List[int] = [self._audio_duration_ms(path) for _, path in chapter_paths]
        concat_lines = []
        for _, path in chapter_paths:
            safe_path = str(path).replace("'", "'\\''")
            concat_lines.append(f"file '{safe_path}'")
        concat_list.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        book_title = str(self.book.get("title") or self.book.get("book_id") or "Audiobook")
        meta_title = book_title if arc == "main" else f"{book_title} {arc_display_name(arc)}"
        meta_lines = [
            ";FFMETADATA1",
            f"title={self._escape_ffmeta(meta_title)}",
            "genre=Audiobook",
            "",
        ]
        cursor = 0
        for index, (number, _) in enumerate(chapter_paths):
            duration = durations[index] if index < len(durations) else 0
            end = cursor + max(1, duration)
            internal_number = mapping[number]
            meta_lines.extend([
                "[CHAPTER]", "TIMEBASE=1/1000", f"START={cursor}", f"END={end}",
                f"title={self._escape_ffmeta(title_for_chapter(self.book, internal_number))}", "",
            ])
            cursor = end
        meta_path.write_text("\n".join(meta_lines), encoding="utf-8")
        is_full_arc = first == min(all_numbers) and last == max(all_numbers)
        if is_full_arc and arc == "main":
            output_name = f"{self.book.get('book_id', 'book')}.m4b"
        elif is_full_arc:
            output_name = f"{self.book.get('book_id', 'book')}_{arc}.m4b"
        elif arc == "main":
            output_name = f"{self.book.get('book_id', 'book')}_{first:03d}-{last:03d}.m4b"
        else:
            output_name = f"{self.book.get('book_id', 'book')}_{arc}_{first:03d}-{last:03d}.m4b"
        output = self.book_dir / "output" / output_name
        command = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(meta_path), "-map", "0:a", "-map_metadata", "1",
            "-c:a", "aac", "-b:a", "128k", "-vn", str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise PipelineError(f"ffmpeg 导出 m4b 失败：{detail[-1000:]}")
        return output

    @staticmethod
    def _escape_ffmeta(value: Any) -> str:
        text = str(value or "")
        return text.replace("\\", "\\\\").replace("\n", "\\n").replace("=", "\\=").replace(";", "\\;")

    @staticmethod
    def _audio_duration_ms(path: Path) -> int:
        try:
            with wave.open(str(path), "rb") as handle:
                if handle.getframerate():
                    return int(handle.getnframes() * 1000 / handle.getframerate())
        except (wave.Error, OSError):
            pass
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            try:
                return int(float(result.stdout.strip()) * 1000)
            except (TypeError, ValueError):
                pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

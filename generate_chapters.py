#!/usr/bin/env python3
"""按小说原始章节号增量生成 Alexandria 有声书。

用法：
    ./generate_chapters.py 729 10
    ./generate_chapters.py 729 20 --continue
    ./generate_chapters.py --arc xian 1 5
    ./generate_chapters.py --arc outside 1 3 --plan

脚本只接受小说章节号。内部导入切分号由 cli.py 的严格正文映射自动处理，
生成完成后会原子发布到 output/chapters，Audiobookshelf 的 File Watcher
会看到新增或更新的章节。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从指定小说章节开始，连续生成 N 章并发布到 Audiobookshelf 目录"
    )
    parser.add_argument("start", type=int, help="起始小说章节号")
    parser.add_argument("count", type=int, nargs="?", default=1, help="连续生成的小说章节数，默认 1")
    parser.add_argument("--book", default="fanren", help="书籍 ID，默认 fanren")
    parser.add_argument("--arc", default="main", help="章节分区：main、xian/仙界篇、outside/外传")
    parser.add_argument("--books-dir", help="书籍项目根目录")
    parser.add_argument("--force", action="store_true", help="忽略分析、摘要和音频缓存，重做范围内章节")
    parser.add_argument("--continue", dest="continue_", action="store_true", help="从范围内第一个未完成章节继续")
    parser.add_argument("--plan", action="store_true", help="只检查并打印章节映射，不调用 Codex/TTS")
    return parser


def _pipeline(args: argparse.Namespace) -> cli.BookPipeline:
    books_dir = cli.resolve_books_dir(args.books_dir)
    book_dir = cli.book_root(books_dir, args.book)
    if not book_dir.exists():
        raise cli.PipelineError(f"书籍项目不存在：{book_dir}；请先运行 init")
    return cli.BookPipeline(book_dir)


def _selected(pipeline: cli.BookPipeline, args: argparse.Namespace) -> list[int]:
    return cli.select_chapters(
        pipeline.book,
        first=args.start,
        count=args.count,
        continue_=args.continue_ and not args.force,
        book_dir=pipeline.book_dir,
        arc=args.arc,
    )


def _print_plan(pipeline: cli.BookPipeline, args: argparse.Namespace) -> int:
    selected = _selected(pipeline, args)
    if not selected:
        print("范围内没有需要继续处理的小说章节")
        return 0
    arc = cli.normalize_arc(args.arc)
    print(f"书籍：{pipeline.book.get('title') or args.book}")
    print(
        f"分区：{cli.arc_display_name(arc)}；章节："
        f"{pipeline.novel_chapter_number(selected[0])} - "
        f"{pipeline.novel_chapter_number(selected[-1])}（{len(selected)} 章）"
    )
    for internal_number in selected:
        novel_number = pipeline.novel_chapter_number(internal_number)
        title = cli.title_for_chapter(pipeline.book, internal_number)
        output_name = cli.chapter_audio_filename(
            pipeline.book_dir, pipeline.book, internal_number, arc=arc, novel_number=novel_number
        )
        print(f"{novel_number:>5}  {title}  -> output/chapters/{output_name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.start <= 0:
        print("error: start 必须是正整数", file=sys.stderr)
        return 2
    if args.count <= 0:
        print("error: count 必须是正整数", file=sys.stderr)
        return 2
    try:
        pipeline = _pipeline(args)
        if args.plan:
            return _print_plan(pipeline, args)

        command = [
            "run",
            "--book", args.book,
            "--arc", args.arc,
            "--from", str(args.start),
            "--count", str(args.count),
        ]
        if args.books_dir:
            command.extend(["--books-dir", args.books_dir])
        if args.force:
            command.append("--force")
        elif args.continue_:
            command.append("--continue")
        return cli.main(command)
    except cli.PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

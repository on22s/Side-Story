#!/usr/bin/env python3
"""Prepare, publish, and bind real-reference Alexandria voice profiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from voice_profiles import (  # noqa: E402
    VoiceProfileError,
    bind_character_profile,
    inspect_reference,
    prepare_reference,
    quality_warnings,
    register_profile,
    validate_reference,
    write_manifest,
)


def _manifest(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceProfileError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise VoiceProfileError("unsupported voice profile manifest")
    return payload


def command_inspect(args):
    metrics = inspect_reference(args.audio)
    print(json.dumps({
        "metrics": metrics.__dict__,
        "errors": validate_reference(metrics),
        "warnings": quality_warnings(metrics),
    }, ensure_ascii=False, indent=2))
    return 1 if validate_reference(metrics) else 0


def command_prepare(args):
    metrics = prepare_reference(
        args.input,
        args.output,
        start_seconds=args.start,
        duration_seconds=args.duration,
    )
    manifest_path = args.manifest or args.output.with_suffix(".profile.json")
    payload = write_manifest(
        manifest_path,
        audio_path=args.output,
        metrics=metrics,
        speaker=args.speaker,
        transcript=args.text,
        description=args.description,
        language=args.language,
        source_url=args.source_url,
        source_title=args.source_title,
        rights_basis=args.rights_basis,
        rights_confirmed=args.rights_confirmed,
        x_vector_only_mode=args.x_vector_only,
    )
    print(json.dumps({"manifest": str(manifest_path), **payload}, ensure_ascii=False, indent=2))
    return 0


def command_publish(args):
    manifest = _manifest(args.manifest)
    response = register_profile(
        args.endpoint,
        args.profile_id,
        manifest,
        force=args.force,
        timeout=args.timeout,
    )
    result = {"remote": response}
    if args.book_dir and args.character:
        result["binding"] = bind_character_profile(
            args.book_dir,
            args.character,
            args.profile_id,
            manifest,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_bind(args):
    result = bind_character_profile(
        args.book_dir,
        args.character,
        args.profile_id,
        _manifest(args.manifest),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="inspect an existing WAV reference")
    inspect_parser.add_argument("audio", type=Path)
    inspect_parser.set_defaults(handler=command_inspect)

    prepare_parser = subparsers.add_parser(
        "prepare", help="trim and normalise a separated reference, then write its manifest"
    )
    prepare_parser.add_argument("--input", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    prepare_parser.add_argument("--manifest", type=Path)
    prepare_parser.add_argument("--start", type=float)
    prepare_parser.add_argument("--duration", type=float)
    prepare_parser.add_argument("--speaker", required=True)
    prepare_parser.add_argument("--text", default="")
    prepare_parser.add_argument("--description", default="")
    prepare_parser.add_argument("--language", default="Chinese")
    prepare_parser.add_argument("--source-url", default="")
    prepare_parser.add_argument("--source-title", default="")
    prepare_parser.add_argument("--rights-basis", required=True)
    prepare_parser.add_argument("--rights-confirmed", action="store_true", required=True)
    prepare_parser.add_argument("--x-vector-only", action="store_true")
    prepare_parser.set_defaults(handler=command_prepare)

    publish_parser = subparsers.add_parser(
        "publish", help="register a prepared reference and optionally bind it to a character"
    )
    publish_parser.add_argument("--manifest", type=Path, required=True)
    publish_parser.add_argument("--profile-id", required=True)
    publish_parser.add_argument("--endpoint", default="http://127.0.0.1:18000/tts")
    publish_parser.add_argument("--book-dir", type=Path)
    publish_parser.add_argument("--character")
    publish_parser.add_argument("--force", action="store_true")
    publish_parser.add_argument("--timeout", type=float, default=180.0)
    publish_parser.set_defaults(handler=command_publish)

    bind_parser = subparsers.add_parser("bind", help="bind an already registered profile")
    bind_parser.add_argument("--manifest", type=Path, required=True)
    bind_parser.add_argument("--profile-id", required=True)
    bind_parser.add_argument("--book-dir", type=Path, required=True)
    bind_parser.add_argument("--character", required=True)
    bind_parser.set_defaults(handler=command_bind)
    return parser


def main():
    args = build_parser().parse_args()
    if getattr(args, "book_dir", None) and bool(getattr(args, "character", None)) is False:
        raise VoiceProfileError("--book-dir and --character must be supplied together")
    if getattr(args, "character", None) and getattr(args, "book_dir", None) is None:
        raise VoiceProfileError("--book-dir and --character must be supplied together")
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VoiceProfileError as exc:
        print(f"voice-profile error: {exc}", file=sys.stderr)
        raise SystemExit(2)

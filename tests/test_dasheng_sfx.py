from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cli


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.data


class DashengSFXClientTests(unittest.TestCase):
    def test_client_caches_valid_wav(self) -> None:
        wav = b"RIFF" + (b"\x00" * 4) + b"WAVE" + (b"\x00" * 40)
        with tempfile.TemporaryDirectory() as directory:
            config = {
                "sfx": {
                    "provider": "dasheng",
                    "url": "http://127.0.0.1:18100/sfx",
                    "cache_dir": directory,
                    "seed": 7,
                    "steps": 2,
                }
            }
            client = cli.DashengSFXClient(config, Path(directory) / "book")
            record = {"category": "movement", "description": "a wooden door creaking open"}
            with mock.patch("cli.ensure_xc_sfx_service") as ensure:
                with mock.patch(
                    "cli.urllib.request.urlopen", return_value=_FakeResponse(wav)
                ) as urlopen:
                    first = client.generate("door_wood", record)
                    second = client.generate("door_wood", record)

            self.assertEqual(first, second)
            self.assertTrue(first.is_file())
            self.assertEqual(first.read_bytes(), wav)
            urlopen.assert_called_once()
            ensure.assert_called_once()
            self.assertTrue(first.with_suffix(".json").is_file())

    def test_pipeline_resolves_generated_file_and_preserves_timeline_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "generated.wav"
            generated.write_bytes(b"RIFF" + (b"\x00" * 4) + b"WAVE" + (b"\x00" * 40))
            builtin = root / "builtin.wav"
            builtin.write_bytes(generated.read_bytes())
            pipeline = object.__new__(cli.BookPipeline)
            pipeline.book_dir = root
            pipeline.config = {
                "sfx": {
                    "enabled": True,
                    "provider": "dasheng",
                    "url": "http://127.0.0.1:18100/sfx",
                    "fallback_to_manifest": False,
                }
            }
            pipeline.sfx_manifest = {
                "door_wood": {
                    "path": str(builtin),
                    "paths": [str(builtin)],
                    "category": "movement",
                    "description": "木门开启",
                    "gain_db": -12.0,
                    "loop": False,
                }
            }
            pipeline._sound_effects_enabled = lambda: True
            script = [{
                "line_id": 1,
                "effects": [{
                    "cue": "door_wood",
                    "position": "after",
                    "offset_ms": 250,
                    "gain_db": -2,
                    "duration_ms": 1200,
                    "loop": False,
                }],
            }]
            with mock.patch.object(
                cli.DashengSFXClient, "generate", return_value=generated
            ) as generate:
                events = pipeline._collect_sound_effect_events(
                    script, [{"line_id": 1, "start_ms": 1000, "end_ms": 1800}]
                )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["file"], str(generated))
            self.assertTrue(events[0]["generated"])
            self.assertEqual(events[0]["start_ms"], 2050)
            self.assertEqual(events[0]["duration_ms"], 1200)
            self.assertEqual(events[0]["gain_db"], -14.0)
            generate.assert_called_once_with("door_wood", pipeline.sfx_manifest["door_wood"])

    def test_builtin_provider_generates_unknown_cue_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "generated.wav"
            generated.write_bytes(b"RIFF" + (b"\x00" * 4) + b"WAVE" + (b"\x00" * 40))
            pipeline = object.__new__(cli.BookPipeline)
            pipeline.book_dir = root
            pipeline.config = {
                "sfx": {
                    "enabled": True,
                    "provider": "builtin",
                    "auto_generate_missing": True,
                    "fallback_to_manifest": False,
                }
            }
            pipeline.sfx_manifest = {}
            pipeline._sound_effects_enabled = lambda: True
            script = [{
                "line_id": 7,
                "effects": [{
                    "cue": "ship_horn",
                    "position": "during",
                    "offset_ms": 0,
                    "gain_db": 0,
                    "duration_ms": 0,
                    "loop": False,
                }],
            }]
            with mock.patch.object(
                cli.DashengSFXClient, "generate", return_value=generated
            ) as generate:
                events = pipeline._collect_sound_effect_events(
                    script, [{"line_id": 7, "start_ms": 1200, "end_ms": 2200}]
                )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["cue"], "ship_horn")
            self.assertEqual(events[0]["file"], str(generated))
            self.assertTrue(events[0]["generated"])
            generate.assert_called_once_with(
                "ship_horn", pipeline.sfx_manifest["ship_horn"]
            )

    def test_builtin_provider_prefers_existing_static_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            builtin = root / "builtin.wav"
            builtin.write_bytes(b"RIFF" + (b"\x00" * 4) + b"WAVE" + (b"\x00" * 40))
            pipeline = object.__new__(cli.BookPipeline)
            pipeline.book_dir = root
            pipeline.config = {
                "sfx": {
                    "enabled": True,
                    "provider": "builtin",
                    "auto_generate_missing": True,
                }
            }
            pipeline.sfx_manifest = {
                "door_wood": {
                    "path": str(builtin),
                    "paths": [str(builtin)],
                    "category": "movement",
                    "gain_db": -12.0,
                    "loop": False,
                }
            }
            pipeline._sound_effects_enabled = lambda: True
            script = [{
                "line_id": 1,
                "effects": [{
                    "cue": "door_wood",
                    "position": "during",
                    "offset_ms": 0,
                    "gain_db": 0,
                    "duration_ms": 0,
                    "loop": False,
                }],
            }]
            with mock.patch.object(cli.DashengSFXClient, "generate") as generate:
                events = pipeline._collect_sound_effect_events(
                    script, [{"line_id": 1, "start_ms": 0, "end_ms": 500}]
                )

            self.assertEqual(events[0]["file"], str(builtin))
            self.assertFalse(events[0]["generated"])
            generate.assert_not_called()

    def test_service_failure_falls_back_to_existing_static_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            builtin = root / "builtin.wav"
            builtin.write_bytes(b"RIFF" + (b"\x00" * 4) + b"WAVE" + (b"\x00" * 40))
            pipeline = object.__new__(cli.BookPipeline)
            pipeline.book_dir = root
            pipeline.config = {
                "sfx": {
                    "enabled": True,
                    "provider": "dasheng",
                    "auto_generate_missing": True,
                    "fallback_to_manifest": True,
                }
            }
            pipeline.sfx_manifest = {
                "door_wood": {
                    "path": str(builtin),
                    "paths": [str(builtin)],
                    "category": "movement",
                    "gain_db": -12.0,
                    "loop": False,
                }
            }
            pipeline._sound_effects_enabled = lambda: True
            script = [{
                "line_id": 1,
                "effects": [{
                    "cue": "door_wood",
                    "position": "during",
                    "offset_ms": 0,
                    "gain_db": 0,
                    "duration_ms": 0,
                    "loop": False,
                }],
            }]
            with mock.patch.object(
                cli.DashengSFXClient,
                "generate",
                side_effect=cli.PipelineError("service down"),
            ):
                events = pipeline._collect_sound_effect_events(
                    script, [{"line_id": 1, "start_ms": 0, "end_ms": 500}]
                )

            self.assertEqual(events[0]["file"], str(builtin))
            self.assertFalse(events[0]["generated"])

    def test_service_failure_without_static_asset_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = object.__new__(cli.BookPipeline)
            pipeline.book_dir = root
            pipeline.config = {
                "sfx": {
                    "enabled": True,
                    "provider": "builtin",
                    "auto_generate_missing": True,
                    "fallback_to_manifest": True,
                }
            }
            pipeline.sfx_manifest = {}
            pipeline._sound_effects_enabled = lambda: True
            script = [{
                "line_id": 1,
                "effects": [{
                    "cue": "ship_horn",
                    "position": "during",
                    "offset_ms": 0,
                    "gain_db": 0,
                    "duration_ms": 0,
                    "loop": False,
                }],
            }]
            with mock.patch.object(
                cli.DashengSFXClient,
                "generate",
                side_effect=cli.PipelineError("service down"),
            ):
                with self.assertRaisesRegex(cli.PipelineError, "ship_horn"):
                    pipeline._collect_sound_effect_events(
                        script, [{"line_id": 1, "start_ms": 0, "end_ms": 500}]
                    )

    def test_missing_manifest_asset_is_retained_for_auto_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "effects": {
                        "cave_water": {
                            "file": "cave_water.wav",
                            "category": "ambience",
                            "description": "water echoing underground",
                            "loop": True,
                        }
                    }
                }),
                encoding="utf-8",
            )

            path, effects = cli.load_sfx_manifest({
                "sfx": {
                    "manifest": str(manifest),
                    "provider": "builtin",
                    "auto_generate_missing": True,
                }
            })

            self.assertEqual(path, manifest.resolve())
            self.assertIn("cave_water", effects)
            self.assertEqual(effects["cave_water"]["paths"], [])
            self.assertTrue(effects["cave_water"]["asset_missing"])


if __name__ == "__main__":
    unittest.main()

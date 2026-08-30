from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import cli


def write_silence(path: Path, duration_ms: int, sample_rate: int = 8000) -> None:
    frames = int(duration_ms * sample_rate / 1000)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)


class SoundEffectTests(unittest.TestCase):
    def test_builtin_manifest_is_complete(self) -> None:
        path, manifest = cli.load_sfx_manifest({
            "sfx": {"manifest": str(cli.DEFAULT_SFX_MANIFEST)}
        })
        self.assertEqual(path, cli.DEFAULT_SFX_MANIFEST.resolve())
        self.assertGreaterEqual(len(manifest), 20)
        self.assertIn("sword_clash", manifest)
        self.assertIn("mountain_wind", manifest)
        self.assertTrue(Path(manifest["sword_clash"]["path"]).is_file())
        self.assertGreaterEqual(len(manifest["sword_clash"]["paths"]), 4)

    def test_every_recorded_asset_is_referenced(self) -> None:
        _, manifest = cli.load_sfx_manifest({
            "sfx": {"manifest": str(cli.DEFAULT_SFX_MANIFEST)}
        })
        recorded_root = (cli.DEFAULT_SFX_MANIFEST.parent / "recorded").resolve()
        recorded_files = set(recorded_root.rglob("*.wav"))
        referenced = set()
        for record in manifest.values():
            for raw_path in record.get("paths", []):
                path = Path(raw_path).resolve()
                if path.is_relative_to(recorded_root):
                    referenced.add(path)
        self.assertEqual(len(recorded_files), 28)
        self.assertEqual(referenced, recorded_files)

    def test_cues_are_filtered_and_clamped(self) -> None:
        manifest = {
            "clash": {"loop": False},
            "wind": {"loop": True},
        }
        result = cli.normalize_sound_effects([
            {
                "cue": "clash", "position": "somewhere", "offset_ms": 50000,
                "gain_db": 99, "duration_ms": -1, "loop": True,
            },
            {
                "cue": "wind", "position": "before", "offset_ms": -200,
                "gain_db": -3, "duration_ms": 0, "loop": True,
            },
            {"cue": "missing"},
        ], manifest)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["position"], "during")
        self.assertEqual(result[0]["offset_ms"], 10000)
        self.assertEqual(result[0]["gain_db"], 6.0)
        self.assertFalse(result[0]["loop"])
        self.assertEqual(result[1]["duration_ms"], 15000)

    def test_dialogue_merge_returns_line_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.wav"
            second = root / "second.wav"
            output = root / "dialogue.wav"
            write_silence(first, 200)
            write_silence(second, 300)
            timeline = cli.BookPipeline._merge_wav_files(
                [first, second], ["a", "b"], [None, None], 500, 250, output
            )
            self.assertEqual(timeline, [
                {"line_id": 1, "start_ms": 0, "end_ms": 200},
                {"line_id": 2, "start_ms": 700, "end_ms": 1000},
            ])
            self.assertTrue(output.is_file())

    def test_line_relative_cues_resolve_to_absolute_time(self) -> None:
        _, manifest = cli.load_sfx_manifest({
            "sfx": {"manifest": str(cli.DEFAULT_SFX_MANIFEST)}
        })
        pipeline = object.__new__(cli.BookPipeline)
        pipeline.sfx_manifest = manifest
        pipeline._sound_effects_enabled = lambda: True
        script = [{
            "line_id": 7,
            "effects": [
                {
                    "cue": "sword_whoosh", "position": "before", "offset_ms": -300,
                    "gain_db": 0, "duration_ms": 0, "loop": False,
                },
                {
                    "cue": "sword_clash", "position": "after", "offset_ms": 250,
                    "gain_db": -2, "duration_ms": 0, "loop": False,
                },
            ],
        }]
        events = pipeline._collect_sound_effect_events(
            script, [{"line_id": 7, "start_ms": 1000, "end_ms": 1800}]
        )
        repeated = pipeline._collect_sound_effect_events(
            script, [{"line_id": 7, "start_ms": 1000, "end_ms": 1800}]
        )
        self.assertEqual([event["start_ms"] for event in events], [700, 2050])
        self.assertEqual(events[1]["gain_db"], manifest["sword_clash"]["gain_db"] - 2)
        self.assertEqual([event["file"] for event in events], [event["file"] for event in repeated])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_ffmpeg_overlay_produces_valid_wav(self) -> None:
        _, manifest = cli.load_sfx_manifest({
            "sfx": {"manifest": str(cli.DEFAULT_SFX_MANIFEST)}
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dialogue = root / "dialogue.wav"
            output = root / "mixed.wav"
            write_silence(dialogue, 600, 24000)
            cli.BookPipeline._mix_sound_effects(dialogue, [
                {
                    "cue": "sword_clash",
                    "category": "combat",
                    "file": manifest["sword_clash"]["path"],
                    "gain_db": -12.0,
                    "start_ms": 250,
                    "duration_ms": 0,
                    "loop": False,
                },
                {
                    "cue": "mountain_wind",
                    "category": "ambience",
                    "file": manifest["mountain_wind"]["path"],
                    "gain_db": -28.0,
                    "start_ms": 0,
                    "duration_ms": 1200,
                    "loop": True,
                },
            ], output)
            with wave.open(str(output), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getframerate(), 48000)
                self.assertGreater(handle.getnframes(), 48000)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_chapter_combine_writes_master_timeline_and_m4b(self) -> None:
        _, manifest = cli.load_sfx_manifest({
            "sfx": {"manifest": str(cli.DEFAULT_SFX_MANIFEST)}
        })
        with tempfile.TemporaryDirectory() as directory:
            book_dir = Path(directory)
            chapter_dir = cli.chapter_root(book_dir, 1)
            line_dir = chapter_dir / "lines"
            line_dir.mkdir(parents=True)
            first = line_dir / "line_000001.wav"
            second = line_dir / "line_000002.wav"
            write_silence(first, 350, 24000)
            write_silence(second, 450, 24000)
            pipeline = object.__new__(cli.BookPipeline)
            pipeline.book_dir = book_dir
            pipeline.sfx_manifest = manifest
            pipeline.chapter_label = lambda chapter: f"chapter {chapter}"
            pipeline._sound_effects_enabled = lambda: True
            script = [
                {
                    "line_id": 1, "voice_id": "narrator", "pause_after": 250,
                    "effects": [{
                        "cue": "sword_whoosh", "position": "after", "offset_ms": 0,
                        "gain_db": 0, "duration_ms": 0, "loop": False,
                    }],
                },
                {"line_id": 2, "voice_id": "hero", "effects": []},
            ]
            result = pipeline._combine_chapter_audio(1, script, [first, second])
            self.assertEqual(result, chapter_dir / "audio.m4b")
            self.assertTrue((chapter_dir / "dialogue.wav").is_file())
            self.assertTrue((chapter_dir / "audio.wav").is_file())
            self.assertTrue((chapter_dir / "audio.m4b").is_file())
            timeline = cli.read_json(chapter_dir / "sfx_timeline.json", [])
            self.assertEqual(len(timeline), 1)
            self.assertEqual(timeline[0]["start_ms"], 350)
            probe = subprocess.check_output(
                [
                    "ffprobe", "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=sample_rate,channels",
                    "-of", "default=noprint_wrappers=1",
                    str(chapter_dir / "audio.m4b"),
                ],
                text=True,
            )
            self.assertIn("sample_rate=44100", probe)
            self.assertIn("channels=1", probe)


if __name__ == "__main__":
    unittest.main()

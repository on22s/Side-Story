"""Synthetic exporter regression tests; no optional packages or models needed."""
import ast
import io
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import wave
import zipfile


class SyntheticAudio:
    """Small deterministic audio double; WAV/ZIP output uses real containers."""
    loads = []

    def __init__(self, duration=10):
        self.duration = duration

    def __len__(self):
        return self.duration

    def __add__(self, other):
        return type(self)(len(self) + len(other))

    @classmethod
    def empty(cls):
        return cls(0)

    @classmethod
    def silent(cls, duration):
        return cls(duration)

    @classmethod
    def from_file(cls, path, **kwargs):
        cls.loads.append((Path(path).name, kwargs))
        if Path(path).read_bytes() == b"corrupt":
            raise ValueError("synthetic decode failure")
        return cls()

    def export(self, target, format):
        if format == "wav":
            with wave.open(target if isinstance(target, str) else target, "wb") as wav:
                wav.setparams((1, 2, 1000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * len(self))
        else:
            Path(target).write_bytes(b"synthetic mp3")


def load_export_module():
    """Execute real project code and real pure timeline helpers without models.

    Only optional audio/model imports are omitted; no export method is copied
    or rewritten. Run this file directly from the repository's app directory.
    """
    app_dir = Path(__file__).resolve().parent
    namespace = {"AudioSegment": SyntheticAudio, "TTSEngine": object,
                 "DEFAULT_PAUSE_MS": 500, "SAME_SPEAKER_PAUSE_MS": 250,
                 "sanitize_filename": lambda value: value}
    tts_tree = ast.parse((app_dir / "tts.py").read_text(encoding="utf-8"))
    tts_tree.body = [node for node in tts_tree.body
                     if isinstance(node, ast.FunctionDef) and node.name in
                     ("compute_timeline", "combine_audio_with_pauses")]
    exec(compile(tts_tree, str(app_dir / "tts.py"), "exec"), namespace)
    source_path = Path(os.environ.get("EXPORT_PROJECT_SOURCE", app_dir / "project.py"))
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body
                 if not (isinstance(node, ast.ImportFrom) and
                         node.module in ("tts", "pydub", "utils"))]
    exec(compile(tree, str(source_path), "exec"), namespace)
    return types.SimpleNamespace(**namespace)


def make_manager(module, root, chunks):
    manager = module.ProjectManager(str(root))
    manager.load_chunks = lambda: chunks
    manager._load_pause_defaults = lambda: (500, 250)
    return manager

module = load_export_module()


class SkippedAudioTests(unittest.TestCase):
    def test_exporters_report_each_skip_and_keep_valid_messages(self):
        cases = [([], 0), ([{}], 1),
                 ([{"audio_path": "missing.wav"}], 1),
                 ([{"audio_path": "corrupt.wav"}], 1),
                 ([{}, {"audio_path": "missing.wav"},
                   {"audio_path": "corrupt.wav"}], 3)]
        for exporter in ("merge_audio", "export_audacity", "merge_m4b"):
            for extra, skipped in cases:
                with self.subTest(exporter=exporter, skipped=skipped, extra=extra):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        (root / "valid.wav").write_bytes(b"valid")
                        (root / "corrupt.wav").write_bytes(b"corrupt")
                        valid = {"audio_path": "valid.wav", "speaker": "Narrator", "text": "hello"}
                        manager = make_manager(module, root, [valid] + extra)
                        process = types.SimpleNamespace(returncode=0, stderr="")
                        with patch.object(module.subprocess, "run", return_value=process) as ffmpeg:
                            success, message = getattr(manager, exporter)()
                        self.assertTrue(success)
                        expected = {"merge_audio": "cloned_audiobook.mp3",
                                    "export_audacity": str(root / "audacity_export.zip"),
                                    "merge_m4b": "audiobook.m4b"}[exporter]
                        if skipped:
                            expected += f" ({skipped} chunk(s) skipped — missing/corrupt audio)"
                        self.assertEqual(message, expected)
                        self.assertEqual(ffmpeg.call_count, int(exporter == "merge_m4b"))
                        if exporter == "export_audacity":
                            with zipfile.ZipFile(root / "audacity_export.zip") as archive:
                                self.assertIsNone(archive.testzip())
                                self.assertEqual(archive.namelist(), ["project.lof", "labels.txt", "Narrator.wav"])
                                self.assertEqual(len(archive.read("labels.txt").splitlines()), 1)

    def test_all_missing_or_empty_exports_fail_without_outputs(self):
        for exporter in ("merge_audio", "export_audacity", "merge_m4b"):
            for chunks in ([], [{}, {"audio_path": "absent.wav"}, {"audio_path": "corrupt.wav"}]):
                with self.subTest(exporter=exporter, chunks=chunks):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        (root / "corrupt.wav").write_bytes(b"corrupt")
                        manager = make_manager(module, root, chunks)
                        before = set(root.iterdir())
                        with patch.object(module.subprocess, "run") as ffmpeg:
                            self.assertEqual(getattr(manager, exporter)(), (False, "No audio segments found"))
                        ffmpeg.assert_not_called()
                        self.assertEqual(set(root.iterdir()), before)

    def test_codec_hints_order_and_timeline_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = []
            for suffix in ("mp3", "wav", "flac", "ogg", "custom"):
                name = "valid." + suffix
                (root / name).write_bytes(b"valid")
                chunks.append({"audio_path": name, "speaker": "Narrator"})
            manager = make_manager(module, root, chunks)
            SyntheticAudio.loads = []
            loaded, skipped = manager._load_chunks_with_audio()
            self.assertEqual(skipped, 0)
            self.assertEqual([chunk for chunk, audio in loaded], chunks)
            self.assertEqual(SyntheticAudio.loads,
                             [("valid." + suffix, {"format": suffix, "codec": suffix})
                              for suffix in ("mp3", "wav", "flac", "ogg")] + [("valid.custom", {})])
            self.assertEqual([start for _, _, start in module.compute_timeline(loaded)],
                             [0, 260, 520, 780, 1040])


if __name__ == "__main__":
    unittest.main()

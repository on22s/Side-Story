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


class AtomicAudacityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "audacity_export.zip"
        with zipfile.ZipFile(self.output, "w") as archive:
            archive.writestr("previous.txt", "previous successful export")
        self.old_bytes = self.output.read_bytes()
        self.foreign = self.root / ".audacity-export-unowned"
        self.foreign.mkdir()
        (self.foreign / "keep").write_bytes(b"unowned staging")
        (self.root / "valid.wav").write_bytes(b"valid")
        self.manager = self.make_manager("Narrator")

    def make_manager(self, speaker):
        return make_manager(module, self.root,
                            [{"audio_path": "valid.wav", "speaker": speaker, "text": speaker}])

    def assert_preserved(self):
        self.assertEqual(self.output.read_bytes(), self.old_bytes)
        self.assertEqual((self.foreign / "keep").read_bytes(), b"unowned staging")
        self.assertEqual(list(self.root.glob(".audacity-export-*")), [self.foreign])

    def test_member_write_failure_preserves_old_bytes(self):
        original = zipfile.ZipFile.writestr
        def fail(archive, name, data, *args, **kwargs):
            if name == "labels.txt":
                raise OSError("injected ZIP write failure")
            return original(archive, name, data, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "writestr", fail):
            with self.assertRaisesRegex(OSError, "ZIP write failure"):
                self.manager.export_audacity()
        self.assert_preserved()

    def test_wav_export_failure_preserves_old_bytes(self):
        with patch.object(SyntheticAudio, "export", side_effect=OSError("injected WAV export failure")):
            with self.assertRaisesRegex(OSError, "WAV export failure"):
                self.manager.export_audacity()
        self.assert_preserved()

    def test_zip_close_failure_preserves_old_bytes(self):
        original = zipfile.ZipFile.close
        def fail(archive):
            writing = archive.mode == "w" and archive.fp is not None
            original(archive)
            if writing:
                raise OSError("injected ZIP close failure")
        with patch.object(zipfile.ZipFile, "close", fail):
            with self.assertRaisesRegex(OSError, "ZIP close failure"):
                self.manager.export_audacity()
        self.assert_preserved()

    def test_replace_failure_preserves_old_bytes(self):
        with patch.object(module.os, "replace", side_effect=PermissionError("injected replacement failure")):
            with self.assertRaisesRegex(PermissionError, "replacement failure"):
                self.manager.export_audacity()
        self.assert_preserved()

    def test_success_publishes_complete_closed_zip(self):
        original = os.replace
        def inspect_then_replace(source, target):
            self.assertEqual(self.output.read_bytes(), self.old_bytes)
            self.assertEqual(Path(source).parent.parent, self.root)
            with zipfile.ZipFile(source) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.namelist(), ["project.lof", "labels.txt", "Narrator.wav"])
                with wave.open(io.BytesIO(archive.read("Narrator.wav"))) as wav:
                    self.assertEqual(wav.getnframes(), 10)
            return original(source, target)
        with patch.object(module.os, "replace", inspect_then_replace):
            self.assertEqual(self.manager.export_audacity(), (True, str(self.output)))
        self.assertNotEqual(self.output.read_bytes(), self.old_bytes)
        self.assertEqual(list(self.root.glob(".audacity-export-*")), [self.foreign])

    def test_concurrent_failure_cleans_only_its_own_staging(self):
        ready = threading.Barrier(2)
        failing_cleaned = threading.Event()
        paths, results, errors = {}, {}, {}
        original = os.replace
        def controlled_replace(source, target):
            name = threading.current_thread().name
            paths[name] = Path(source)
            ready.wait(timeout=5)
            if name == "failed":
                raise PermissionError("concurrent injected failure")
            self.assertTrue(failing_cleaned.wait(timeout=5))
            self.assertTrue(Path(source).exists())
            self.assertFalse(paths["failed"].parent.exists())
            self.assertEqual(self.output.read_bytes(), self.old_bytes)
            return original(source, target)
        def run(name):
            try:
                results[name] = self.make_manager(name).export_audacity()
            except BaseException as error:
                errors[name] = error
            finally:
                if name == "failed":
                    failing_cleaned.set()
        with patch.object(module.os, "replace", controlled_replace):
            threads = [threading.Thread(target=run, args=(name,), name=name)
                       for name in ("failed", "successful")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
        self.assertNotEqual(paths["failed"].parent, paths["successful"].parent)
        self.assertIsInstance(errors.get("failed"), PermissionError)
        self.assertNotIn("successful", errors)
        self.assertEqual(results["successful"], (True, str(self.output)))
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("successful.wav", archive.namelist())
        self.assertEqual(list(self.root.glob(".audacity-export-*")), [self.foreign])

    def test_concurrent_successes_publish_whole_archives(self):
        barrier = threading.Barrier(2)
        paths, errors = [], []
        original = os.replace
        def controlled_replace(source, target):
            paths.append(Path(source))
            barrier.wait(timeout=5)
            return original(source, target)
        def run(name):
            try:
                self.make_manager(name).export_audacity()
            except BaseException as error:
                errors.append(error)
        with patch.object(module.os, "replace", controlled_replace):
            threads = [threading.Thread(target=run, args=(name,)) for name in ("first", "second")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertEqual(len(set(paths)), 2)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            self.assertIn(names, [{"project.lof", "labels.txt", "first.wav"},
                                  {"project.lof", "labels.txt", "second.wav"}])
        self.assertEqual(list(self.root.glob(".audacity-export-*")), [self.foreign])


if __name__ == "__main__":
    unittest.main()

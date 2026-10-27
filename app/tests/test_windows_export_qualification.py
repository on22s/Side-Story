"""Regression controls for the Windows qualification harness's own verdicts."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if __debug__:
    spec = importlib.util.spec_from_file_location(
        'windows_export_qualification_harness',
        ROOT / 'tools' / 'windows_export_staging_qualification.py',
    )
    qualification = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qualification)
else:
    qualification = None
import windows_export_staging_directory as windows_directory


@unittest.skipIf(os.name == 'nt', 'Synthetic link controls run on POSIX; native qualification is separate')
@unittest.skipIf(not __debug__, 'Harness deliberately refuses optimized execution')
class WindowsQualificationVerdictTests(unittest.TestCase):
    def test_rename_denial_requires_a_sharing_violation_and_releases_child(self):
        process = SimpleNamespace(live=False, held=False, pid=123,
                                  stdin=None, stdout=None, stderr=None)
        process.poll = lambda: None if process.live else 0

        def hold(_script, root, *, interactive=False):
            self.assertTrue(interactive)
            process.live = process.held = True
            stage = Path(root) / 'stage'
            stage.mkdir()
            (stage / 'payload.bin').write_bytes(b'owned payload')
            return process, stage

        def terminate(_process):
            process.live = process.held = False

        def release(_process):
            self.assertTrue(process.live and process.held)
            process.held = False

        def finish(_process):
            self.assertTrue(process.live and not process.held)
            process.live = False

        original = Path.rename
        for rename_code, probes, expected in (
                (32, (32, 32), None),
                (5, (None, 32), None),
                (5, (None, 5), qualification.UnsupportedCheck),
                (5, (None, 2), AssertionError),
                (5, (None, 3), AssertionError),
                (5, (None, 183), AssertionError),
                (5, (2, 32), AssertionError),
                (5, (3, 32), AssertionError),
                (5, (183, 32), AssertionError),
                (3, (None, 32), AssertionError),
                (183, (None, 32), AssertionError),
                (5, (None, None), AssertionError)):
            with self.subTest(rename_code=rename_code, probes=probes):
                rename_attempts = []
                last_error = {'code': 0}
                invalid = qualification.ctypes.c_void_p(-1).value

                def create_file(path, *_args):
                    code = (probes[1] if Path(path).name == 'stage' else probes[0]) if process.held else None
                    last_error['code'] = code or 0
                    return invalid if code is not None else 123

                api = SimpleNamespace(CreateFileW=create_file,
                                      CloseHandle=lambda _handle: True)

                def rename(path, target):
                    rename_attempts.append(process.held)
                    if process.held:
                        error = PermissionError('synthetic held-window failure')
                        error.winerror = rename_code
                        raise error
                    return original(path, target)

                with patch.object(qualification, 'child_hold', side_effect=hold), \
                        patch.object(qualification, '_terminate', side_effect=terminate), \
                        patch.object(qualification, '_release_child_handles', side_effect=release), \
                        patch.object(qualification, '_finish_interactive_child', side_effect=finish), \
                        patch.object(qualification, '_api', return_value=api), \
                        patch.object(qualification.ctypes, 'get_last_error', create=True,
                                     side_effect=lambda: last_error['code']), \
                        patch.object(Path, 'rename', rename):
                    if expected is None:
                        result = qualification.check_windows_parent_replacement('windows')
                        self.assertEqual(result['rename_refused'], rename_code)
                        self.assertEqual(result['parent_delete_probe_during_hold'], probes[0])
                        self.assertEqual(result['stage_delete_sharing_violation'], 32)
                        self.assertTrue(result['rename_after_handle_release_while_child_alive'])
                        self.assertEqual(rename_attempts, [False, False, True, False, False])
                    else:
                        with self.assertRaises(expected):
                            qualification.check_windows_parent_replacement('windows')
                    self.assertFalse(process.live)

    def test_junction_refusal_cannot_be_inferred_from_unrelated_failure(self):
        events = []

        def mklink(argv, **_kwargs):
            os.symlink(argv[-1], argv[-2], target_is_directory=True)
            return SimpleNamespace(returncode=0, stderr='')

        def reclaim(parents):
            events.append('reclaim')
            link = Path(parents[0]) / '.mp3-merge-reparse'
            return {'removed': [], 'errors': [], 'preserved': [str(link)]}

        class FakeDirectory:
            mode = 'correct'

            def __init__(self, path, expected):
                self.path, self.expected = Path(path), expected

            def __enter__(self):
                is_link = self.path.name == '.mp3-merge-reparse'
                events.append('link' if is_link else 'ordinary')
                if is_link and self.mode == 'ancestor_error':
                    raise qualification.StageDirectoryChanged('synthetic ancestor failure')
                if is_link and self.mode == 'ancestor_permission':
                    raise PermissionError('synthetic ancestor open failure')
                attrs = 0x410 if is_link and self.mode != 'follow' else 0x10
                if is_link and self.mode == 'not_directory':
                    attrs = 0x400
                volume, index = self.expected
                if is_link and self.mode == 'identity_mismatch':
                    index += 1
                info = SimpleNamespace(attributes=attrs, volume=volume,
                                       index_high=index >> 32, index_low=index & 0xffffffff)
                self.stage = SimpleNamespace(information=lambda: info)
                self.check()
                return self

            def __exit__(self, *_args):
                return False

            def check(self):
                if self.stage.information().attributes & 0x400:
                    raise qualification.StageDirectoryChanged('synthetic reparse rejection')

        with patch.object(qualification.subprocess, 'run', side_effect=mklink), \
                patch.object(qualification, 'reclaim_export_staging', side_effect=reclaim), \
                patch.object(windows_directory, 'WindowsStageDirectory', FakeDirectory):
            for mode in ('correct', 'ancestor_error', 'ancestor_permission', 'follow',
                         'identity_mismatch', 'not_directory'):
                with self.subTest(mode=mode):
                    events.clear()
                    FakeDirectory.mode = mode
                    if mode == 'correct':
                        self.assertTrue(qualification.check_windows_reparse('windows'))
                        self.assertEqual(events, ['ordinary', 'link', 'reclaim'])
                    else:
                        expected = PermissionError if mode == 'ancestor_permission' else AssertionError
                        with self.assertRaises(expected):
                            qualification.check_windows_reparse('windows')
                        self.assertEqual(events, ['ordinary', 'link'])

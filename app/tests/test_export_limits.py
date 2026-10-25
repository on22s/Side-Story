"""Finite limits for the legacy whole-buffer export fallback."""
import unittest
from unittest.mock import patch

from pydub import AudioSegment
import project
from export_limits import (MAX_LEGACY_EXPORT_PCM_BYTES, ensure_legacy_pcm_allowed,
                           get_legacy_pcm_bytes)


def plan(frames, channels=2, sample_width=2):
    return {'frames': frames, 'frame_rate': 24000, 'channels': channels,
            'sample_width': sample_width}


class LegacyExportLimitTests(unittest.TestCase):
    def test_exact_ceiling_is_allowed_and_one_frame_over_is_refused(self):
        frame = 2 * 2
        at_limit = plan(MAX_LEGACY_EXPORT_PCM_BYTES // frame)
        self.assertEqual(MAX_LEGACY_EXPORT_PCM_BYTES, get_legacy_pcm_bytes(at_limit))
        ensure_legacy_pcm_allowed(at_limit)
        with self.assertRaisesRegex(ValueError, 'whole-buffer fallback is limited'):
            ensure_legacy_pcm_allowed(plan(at_limit['frames'] + 1))

    def test_invalid_or_missing_plan_is_refused(self):
        for value in (None, {}, {'frames': -1, 'channels': 2, 'sample_width': 2},
                      {'frames': 1, 'channels': 0, 'sample_width': 2},
                      {'frames': 1, 'channels': 2, 'sample_width': 0}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ensure_legacy_pcm_allowed(value)

    def test_project_refuses_before_the_whole_buffer_is_combined(self):
        huge = plan(MAX_LEGACY_EXPORT_PCM_BYTES // 4 + 1)
        with patch.object(project, 'get_combined_source_plan', return_value=huge), \
             patch.object(project, 'combine_audio_with_pauses',
                          side_effect=AssertionError('whole-buffer combine must not run')):
            with self.assertRaisesRegex(ValueError, 'whole-buffer fallback is limited'):
                project._get_legacy_export_audio(
                    [AudioSegment.silent(duration=10, frame_rate=24000)], ['A'], 0, 0, None, None)


if __name__ == '__main__':
    unittest.main()

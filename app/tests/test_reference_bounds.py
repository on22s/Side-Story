import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
import voice_reference_import as vri

class ReferenceBoundsTests(unittest.TestCase):
    def test_long_compressed_and_pcm_inputs_refused_before_export(self):
        for extension in ('flac', 'wav'):
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp, 'input.' + extension)
                sf.write(src, np.zeros(120 * 24000, np.float32), 24000)
                before = src.read_bytes()
                sizes = []
                run = subprocess.run
                def capture(*args, **kwargs):
                    result = run(*args, **kwargs)
                    sizes.append(len(result.stdout))
                    return result
                with patch.object(subprocess, 'run', side_effect=capture):
                    measures, problems = vri.import_reference_audio(str(src), str(Path(tmp, 'out.wav')))
                self.assertEqual({}, measures)
                self.assertIn('too long', problems[0])
                self.assertEqual([31 * 24000 * 2], sizes)
                self.assertEqual([src.name], os.listdir(tmp))
                self.assertEqual(before, src.read_bytes())

    def test_inaccurate_metadata_cannot_admit_long_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, 'long.flac')
            sf.write(src, np.zeros(120 * 24000), 24000)
            dst = Path(tmp, 'out.wav')
            with patch.object(sf, 'info', return_value=SimpleNamespace(duration=1.0)):
                measures, problems = vri.import_reference_audio(str(src), str(dst))
            self.assertEqual({}, measures)
            self.assertIn('at least 31.0s', problems[0])
            self.assertFalse(dst.exists())

    def test_valid_normalized_reference_and_streamed_quality_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, 'valid.flac')
            samples = .2 * np.sin(np.arange(5 * 48000) / 30)
            sf.write(src, np.column_stack([samples, samples]), 48000)
            dst = Path(tmp, 'out.wav')
            measures, problems = vri.import_reference_audio(str(src), str(dst))
            self.assertEqual([], problems)
            self.assertEqual(5, measures['duration_s'])
            self.assertEqual((24000, 1, 'PCM_16'), (sf.info(dst).samplerate, sf.info(dst).channels, sf.info(dst).subtype))
            sf.write(src, np.concatenate([np.ones(2 * 24000), np.zeros(3 * 24000)]), 24000)
            with patch.object(sf, 'read', side_effect=AssertionError('whole-file read')):
                measures = vri.measure_reference_audio(src)
            self.assertEqual(.6, measures['silence_ratio'])
            self.assertEqual(.4, measures['clipping_ratio'])
            self.assertTrue(any('clipped' in p for p in vri.check_reference_audio(measures)))
            self.assertTrue(any('mostly silence' in p for p in vri.check_reference_audio(measures)))

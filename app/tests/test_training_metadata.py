import json
from pathlib import Path
import tempfile
import unittest
from dataset_metadata import get_training_metadata

class TrainingMetadataTests(unittest.TestCase):
    def write_rows(self, root, relative, rows):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def test_incomplete_split_refused_with_and_without_validation_metadata(self):
        for separator in ('/', '\\'):
            for val_metadata in (True, False):
                with self.subTest(separator=separator, val_metadata=val_metadata), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    rows = [{'audio_filepath': 'val' + separator + 'sample.wav', 'text': 'Synthetic.'}]
                    self.write_rows(root, 'metadata.jsonl', rows)
                    if val_metadata:
                        self.write_rows(root, 'val/metadata.jsonl', rows)
                    with self.assertRaisesRegex(ValueError, 'no training metadata'):
                        get_training_metadata(tmp)

    def test_valid_split_excludes_validation_and_keeps_legacy_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = [{'audio_filepath': 'train/sample.wav', 'text': 'Training.'}]
            val = [{'audio_filepath': 'val/sample.wav', 'text': 'Validation.'}]
            self.write_rows(root, 'metadata.jsonl', train + val)
            self.write_rows(root, 'train/metadata.jsonl', train)
            self.write_rows(root, 'val/metadata.jsonl', val)
            self.assertEqual((train, True), get_training_metadata(tmp))
        for key, path in (('audio_filepath', 'sample.wav'), ('audio_filepath', 'train/sample.wav'), ('audio', 'train/sample.wav')):
            with self.subTest(key=key, path=path), tempfile.TemporaryDirectory() as tmp:
                rows = [{key: path, 'text': 'Legacy.'}]
                self.write_rows(Path(tmp), 'metadata.jsonl', rows)
                self.assertEqual((rows, False), get_training_metadata(tmp))

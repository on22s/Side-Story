import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
from project import CHAPTER_EXPORT_DIR, ProjectManager

class ChapterGroupingTests(unittest.TestCase):
    def test_short_dialogue_and_complete_narration_do_not_create_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProjectManager(tmp)
            chunks = [{'speaker': speaker, 'text': text} for speaker, text in [
                ('NARRATOR', 'Chapter 1'), ('ALICE', 'Hello.'), ('ALICE', 'Hello'),
                ('NARRATOR', 'It ended.'), ('NARRATOR', '“It ended.”'),
                ('NARRATOR', '終わった。'), ('NARRATOR', 'The Awakening'),
                ('ALICE', 'Goodbye!'), ('NARRATOR', 'Chapter 2')]]
            expected = [('Chapter 1', 0, 5), ('The Awakening', 6, 7), ('Chapter 2', 8, 8)]
            self.assertEqual(expected, manager._chapter_groups(chunks, False))
            timeline = [(chunk, bytes(1000), i * 1000) for i, chunk in enumerate(chunks)]
            self.assertEqual([('Chapter 1', 0, 6000), ('The Awakening', 6000, 8000),
                              ('Chapter 2', 8000, 9000)],
                             manager._build_m4b_chapters(timeline, False))

    def test_keyword_dialogue_and_sentences_stay_inside_real_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProjectManager(tmp)
            chunks = [{'speaker': speaker, 'text': text} for speaker, text in [
                ('NARRATOR', 'Chapter 1'), ('ALICE', 'Book me a room.'),
                ('ALICE', 'Chapter two'), ('NARRATOR', 'Part of her wanted to leave.'),
                ('NARRATOR', 'Book me a room!'), ('NARRATOR', '"Section one"'),
                ('NARRATOR', 'Chapter 2')]]
            expected = [('Chapter 1', 0, 5), ('Chapter 2', 6, 6)]
            self.assertEqual(expected, manager._chapter_groups(chunks, False))
            timeline = [(chunk, bytes(1000), i * 1000) for i, chunk in enumerate(chunks)]
            self.assertEqual([('Chapter 1', 0, 6000), ('Chapter 2', 6000, 7000)],
                             manager._build_m4b_chapters(timeline, False))

    def test_long_keyword_heading_is_preserved_but_long_keyword_sentence_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProjectManager(tmp)
            title = 'Chapter 1: ' + 'A very long descriptive title ' * 3
            chunks = [{'speaker': 'NARRATOR', 'text': title},
                      {'speaker': 'NARRATOR', 'text': 'Part of the story ' * 6 + 'ended.'},
                      {'speaker': 'ALICE', 'text': 'Book ' + 'a long request ' * 7},
                      {'speaker': 'NARRATOR', 'text': 'Chapter 2'}]
            self.assertEqual([(title.strip(), 0, 2), ('Chapter 2', 3, 3)],
                             manager._chapter_groups(chunks, False))

    def test_punctuated_numbered_headings_preserve_m4b_and_export_audio_boundaries(self):
        for labels in (('Chapter 1.', 'Chapter 2.'), ('Chapter I.', 'Chapter II.')):
            with self.subTest(labels=labels), tempfile.TemporaryDirectory() as tmp:
                manager = ProjectManager(tmp)
                Path(manager.voicelines_dir).mkdir(exist_ok=True)
                chunks = [{'index': i, 'speaker': speaker, 'text': text,
                           'audio_path': f'voicelines/c{i}.wav'}
                          for i, (speaker, text) in enumerate([
                              ('NARRATOR', labels[0]), ('ALICE', 'First scene.'),
                              ('NARRATOR', labels[1]), ('ALICE', 'Second scene.')])]
                samples = []
                for i, chunk in enumerate(chunks):
                    pcm = np.full(2400, 1000 * (i + 1), dtype=np.int16)
                    sf.write(Path(tmp, chunk['audio_path']), pcm, 24000, subtype='PCM_16')
                    samples.append(pcm)
                expected = [(labels[0], 0, 1), (labels[1], 2, 3)]
                self.assertEqual(expected, manager._chapter_groups(chunks, False))
                with patch.object(manager, 'load_chunks', return_value=chunks), \
                     patch.object(manager, '_load_pause_defaults', return_value=(0, 0)):
                    pairs, skipped = manager._load_chunks_with_audio()
                    self.assertEqual(0, skipped)
                    timeline = [(chunk, segment, i * 100) for i, (chunk, segment) in enumerate(pairs)]
                    self.assertEqual([(labels[0], 0, 200), (labels[1], 200, 400)],
                                     manager._build_m4b_chapters(timeline, False))
                    ok, message = manager.export_chapters(fmt='wav')
                    self.assertTrue(ok, message)
                output = Path(tmp, CHAPTER_EXPORT_DIR)
                manifest = json.loads((output / 'manifest.json').read_text())
                self.assertEqual([[0, 1], [2, 3]], [row['chunks'] for row in manifest['chapters']])
                self.assertEqual(2, len(list(output.glob('*.wav'))))
                for index, row in enumerate(manifest['chapters']):
                    actual, rate = sf.read(output / row['file'], dtype='int16')
                    self.assertEqual(24000, rate)
                    np.testing.assert_array_equal(np.concatenate(samples[index * 2:index * 2 + 2]), actual)

    def test_no_heading_fallback_and_explicit_per_chunk_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProjectManager(tmp)
            chunks = [{'speaker': 'ALICE', 'text': 'Hello.'},
                      {'speaker': 'NARRATOR', 'text': 'It ended.'}]
            expected = [('[ALICE] Hello.', 0, 0), ('[NARRATOR] It ended.', 1, 1)]
            self.assertEqual(expected, manager._chapter_groups(chunks, False))
            self.assertEqual(expected, manager._chapter_groups(chunks, True))
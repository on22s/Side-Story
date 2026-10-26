"""Raw context capture preserves source coordinates without granting crop authority."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from audio_generation_owner import (AudioGenerationCancelled, AudioGenerationOwner,
    ensure_audio_generation_owner, get_audio_generation_claim_id)
from audio_validation import GeneratedAudioError
from experiments.plan_dialogue_continuity import get_continuity_experiment_packet
from experiments.render_dialogue_continuity import (get_hidden_context_capture_requests,
    save_hidden_context_capture_pair)
from experiments.run_dialogue_continuity import run_owned_hidden_context_pair
from synthesis_input import MAX_TEXT
from tests import test_dialogue_continuity_render as render_fixtures
from tests import test_dialogue_continuity_controller as owner_fixtures


class HiddenContextCaptureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = render_fixtures.ContinuityRenderTests()
        self.fixture.setUp()
        self.rows = [
            {'uid': 'before', 'speaker': 'NARRATOR',
             'text': 'ignored one two\tthree four five six'},
            {'uid': 'authored', 'speaker': 'Anna', 'text': '“Éva, e\u0301?🙂”  Yes—yes?',
             'instruct': '', 'pause_after': 0},
            {'uid': 'after', 'speaker': 'NARRATOR',
             'text': 'one two three four five ignored'},
        ]
        self.raw, self.packet = self.packet_for(self.rows)

    def packet_for(self, rows):
        raw = json.dumps({'version': 1, 'narrator_speakers': ['NARRATOR'],
                          'entries': rows}).encode()
        return raw, get_continuity_experiment_packet(raw)

    def capture(self, destination, engine=None, packet=None):
        return save_hidden_context_capture_pair(engine or self.fixture.engine(), self.raw,
            packet or self.packet, 1, self.fixture.voices, destination)

    def test_exact_unicode_spans_context_provenance_and_manual_choices(self):
        before = copy.deepcopy(self.packet)
        requests = get_hidden_context_capture_requests(self.packet, 1)
        self.assertEqual({'hidden_following', 'hidden_sandwich'}, set(requests))
        for arm, request in requests.items():
            contract = request['hidden_context']
            start, end = contract['authored_span_in_request']
            self.assertEqual(self.rows[1]['text'], request['text'][start:end])
            self.assertEqual('unicode_code_points', contract['offset_unit'])
            self.assertEqual('', request['instruct'])
            self.assertEqual(0, request['pause_after'])
            self.assertEqual('not_applied_to_raw_audio', contract['pause_after_application'])
            self.assertEqual('one two three four five', contract['following'])
            for side, provenance in request['context_provenance'].items():
                if provenance is None:
                    continue
                source = self.rows[provenance['row_index']]
                left, right = provenance['source_span']
                out_left, out_right = provenance['request_span']
                self.assertEqual(source['text'][left:right], request['text'][out_left:out_right])
                self.assertEqual(source['speaker'], provenance['speaker'])
            self.assertEqual(0 if arm == 'hidden_following' else len('two\tthree four five six '), start)
        self.assertEqual('two\tthree four five six',
                         requests['hidden_sandwich']['hidden_context']['preceding'])
        self.assertEqual(before, self.packet)

    def test_context_digest_tracks_audible_choices_not_unselected_neighbor_data(self):
        original = get_hidden_context_capture_requests(self.packet, 1)
        rows = copy.deepcopy(self.rows)
        rows[0].update(uid='new-provenance', speaker='Someone',
                       text='different ignored prefix two\tthree four five six')
        rows[2]['text'] = 'one two three four five a different unused suffix'
        _, packet = self.packet_for(rows)
        unchanged = get_hidden_context_capture_requests(packet, 1)
        for arm in original:
            self.assertEqual(original[arm]['context_contract_sha256'],
                             unchanged[arm]['context_contract_sha256'])
        rows[2]['text'] = 'changed two three four five'
        _, packet = self.packet_for(rows)
        changed = get_hidden_context_capture_requests(packet, 1)
        for arm in original:
            self.assertNotEqual(original[arm]['context_contract_sha256'],
                                changed[arm]['context_contract_sha256'])

    def test_edge_rows_and_overlong_whole_context_words_refuse(self):
        for index in (0, 2, -1, True, None):
            with self.subTest(index=index), self.assertRaises(ValueError):
                get_hidden_context_capture_requests(self.packet, index)
        rows = copy.deepcopy(self.rows)
        rows[2]['text'] = 'x' * 257
        _, packet = self.packet_for(rows)
        with self.assertRaisesRegex(ValueError, '256'):
            get_hidden_context_capture_requests(packet, 1)
        rows = copy.deepcopy(self.rows)
        requests = get_hidden_context_capture_requests(self.packet, 1)
        overhead = len(requests['hidden_sandwich']['text']) - len(rows[1]['text'])
        rows[1]['text'] = 'x' * (MAX_TEXT - overhead)
        _, packet = self.packet_for(rows)
        self.assertEqual(MAX_TEXT, len(get_hidden_context_capture_requests(packet, 1)['hidden_sandwich']['text']))
        rows[1]['text'] += 'x'
        _, packet = self.packet_for(rows)
        with self.assertRaisesRegex(ValueError, 'text limit'):
            get_hidden_context_capture_requests(packet, 1)
        rows[1]['text'] = 'x' * MAX_TEXT
        _, packet = self.packet_for(rows)
        with self.assertRaisesRegex(ValueError, 'text limit'):
            get_hidden_context_capture_requests(packet, 1)

    def test_owned_raw_pair_records_actual_bytes_and_target_voice_for_both_variants(self):
        with tempfile.TemporaryDirectory() as directory, ensure_audio_generation_owner(
                AudioGenerationOwner('a' * 32, self.fixture.admit)):
            destination = Path(directory) / 'pair'
            receipt = self.capture(destination)
            self.assertEqual(2, receipt['version'])
            self.assertEqual('hidden_context_raw_capture', receipt['kind'])
            self.assertEqual(receipt, json.loads((destination / 'receipt.json').read_text(encoding='utf-8')))
            self.assertEqual(2, len(self.fixture.calls))
            for arm, captured in receipt['arms'].items():
                data = (destination / (arm + '.wav')).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), captured['audio']['sha256'])
                self.assertTrue(captured['submitted_request_match'])
                start, end = captured['authored_span_in_submitted']
                self.assertEqual(self.rows[1]['text'], captured['speech_input']['text'][start:end])
            self.assertEqual(['Anna', 'Anna'], [call[2] for call in self.fixture.calls])
            self.assertEqual(self.fixture.calls[0][3], self.fixture.calls[1][3])
            self.assertEqual({'Anna': 42}, receipt['seeds'])
            self.assertIn('unqualified', receipt['qualification'])
            original_hashes = {arm: value['audio']['sha256']
                               for arm, value in receipt['arms'].items()}
            rows = copy.deepcopy(self.rows)
            rows[1]['pause_after'] = 325
            self.raw, self.packet = self.packet_for(rows)
            delayed = self.capture(Path(directory) / 'recorded-pause')
            for arm, captured in delayed['arms'].items():
                self.assertEqual(325, captured['request']['pause_after'])
                self.assertEqual('not_applied_to_raw_audio',
                    captured['request']['hidden_context']['pause_after_application'])
                self.assertEqual(original_hashes[arm], captured['audio']['sha256'])
                self.assertNotEqual(receipt['arms'][arm]['request']['context_contract_sha256'],
                                    captured['request']['context_contract_sha256'])

    def test_changed_submitted_text_never_receives_guessed_author_coordinates(self):
        engine = self.fixture.engine()
        original = engine.generate_voice_result
        def prepare(*args, **kwargs):
            result = original(*args, **kwargs)
            result.speech_input['text'] += '.'
            return result
        engine.generate_voice_result = prepare
        with tempfile.TemporaryDirectory() as directory, ensure_audio_generation_owner(
                AudioGenerationOwner('a' * 32, self.fixture.admit)):
            receipt = self.capture(Path(directory) / 'pair', engine)
            for captured in receipt['arms'].values():
                self.assertFalse(captured['submitted_request_match'])
                self.assertIsNone(captured['authored_span_in_submitted'])
                self.assertEqual('unresolved_preparation', captured['submitted_span_status'])

    def test_failed_stale_cancelled_and_forged_plan_cannot_publish_raw_pair(self):
        for failure in ('false', 'stale', 'cancel', 'forged_plan'):
            self.fixture.cancelled = False
            self.fixture.calls = []
            packet = copy.deepcopy(self.packet)
            if failure == 'forged_plan':
                packet['plan']['rows'][1]['baseline']['text'] = 'Forged source.'
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / 'pair'
                with ensure_audio_generation_owner(AudioGenerationOwner('a' * 32, self.fixture.admit)):
                    with self.assertRaises((GeneratedAudioError, AudioGenerationCancelled, ValueError)):
                        self.capture(destination, self.fixture.engine(failure), packet)
                self.assertFalse(destination.exists())
                self.assertFalse(list(Path(directory).glob('.continuity-*')))
                if failure == 'forged_plan':
                    self.assertEqual([], self.fixture.calls)

    def test_hidden_controller_uses_real_owner_and_shared_cleanup_order(self):
        events = []
        with owner_fixtures.isolated_core_ownership(events) as (core, state):
            def render(*args):
                self.assertEqual(core._task_claims['audio']['id'], get_audio_generation_claim_id())
                events.append('capture')
                return {'uid': 'fixture'}
            with patch('experiments.run_dialogue_continuity.save_hidden_context_capture_pair', render):
                self.assertEqual({'uid': 'fixture'}, run_owned_hidden_context_pair(
                    core, b'', {}, 1, {}, 'unused'))
            self.assertEqual(['capture', 'cleanup', 'release'], events)
            self.assertFalse(state['audio']['running'])
            self.assertEqual({}, core._task_claims)

    def test_cli_invalid_context_and_seed_fail_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.json').write_bytes(self.raw)
            (root / 'voices.json').write_text(json.dumps({'Anna': {'type': 'custom', 'seed': -1}}))
            (root / 'config.json').write_text(json.dumps({'tts': {'mode': 'local'}}))
            env = {key: value for key, value in os.environ.items() if key != 'ALEXANDRIA_DATA_DIR'}
            long_rows = copy.deepcopy(self.rows)
            long_rows[1]['text'] = 'x' * MAX_TEXT
            long_raw, _ = self.packet_for(long_rows)
            cases = ((0, 'neighboring', self.raw), (1, 'seed', self.raw),
                     (1, 'text limit', long_raw))
            for case, (row, message, raw) in enumerate(cases):
                (root / 'source.json').write_bytes(raw)
                output = root / ('output-' + str(case))
                result = subprocess.run([sys.executable, '-m', 'experiments.run_dialogue_continuity',
                    '--input', str(root / 'source.json'), '--voices', str(root / 'voices.json'),
                    '--config', str(root / 'config.json'), '--out', str(output), '--row', str(row),
                    '--capture-hidden-context'], cwd=Path(__file__).resolve().parents[1],
                    env=env, capture_output=True, timeout=20)
                self.assertEqual(2, result.returncode)
                self.assertIn(message, result.stderr.decode())
                self.assertFalse(output.exists())

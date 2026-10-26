"""Bounded CPU workflow for baseline/deterministic continuity pairs."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from experiments import dialogue_continuity_eval as ev


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'experiments' / 'fixtures' / 'dialogue_continuity_passage.json'


def write_wav(path, payload=b'fixture'):
    path = Path(path)
    path.write_bytes(b'')
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes((payload * 2000)[:4000])


class DialogueContinuityEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.voices = self.root / 'voices.json'
        self.config = self.root / 'config.json'
        self.voices.write_text(json.dumps({
            'NARRATOR': {'type': 'custom', 'seed': 1},
            'Anna': {'type': 'custom', 'seed': 2},
            'Ben': {'type': 'custom', 'seed': 3}}))
        self.config.write_text(json.dumps({'tts': {'mode': 'local', 'device': 'cpu'}}))

    def run_eval(self, name='run', rows=(0, 1), renderer=None, cancel_check=None):
        return ev.run_collection(
            SOURCE, self.voices, self.config, self.root / name,
            selected_rows=list(rows), render_pair=renderer or ev.dry_render_pair,
            cancel_check=cancel_check, source_root=ROOT,
            source_revision={'head': 'test', 'dirty': False})

    def test_cpu_pairs_are_resumable_and_changed_inputs_or_audio_refuse_reuse(self):
        calls = []
        def renderer(*args):
            calls.append(args[0]['uid'])
            return ev.dry_render_pair(*args)
        first = self.run_eval(renderer=renderer)
        self.assertEqual('complete', first['status'])
        self.assertEqual([0, 1], first['completed_rows'])
        self.assertEqual(['passage-000', 'passage-001'], calls)
        state = json.loads((self.root / 'run/pairs/000_passage-000/attempt-1/state.json').read_text())
        self.assertEqual(state['requested']['baseline']['text'],
                         state['arms']['baseline']['submitted_text'])
        self.assertGreaterEqual(len(state['seeds']), 1)
        resumed = self.run_eval(renderer=lambda *args: (_ for _ in ()).throw(AssertionError('rerendered')))
        self.assertEqual(first['identity'], resumed['identity'])
        self.assertEqual([0, 1], resumed['completed_rows'])
        audio = self.root / 'run/pairs/000_passage-000/attempt-1/baseline.wav'
        write_wav(audio, b'changed but valid')
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'audio changed; refusing reuse'):
            self.run_eval(renderer=lambda *args: None)
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'inputs/code changed'):
            ev.run_collection(SOURCE, self.voices, self.config, self.root / 'run',
                selected_rows=[0, 1], render_pair=ev.dry_render_pair, source_root=ROOT,
                source_revision={'head': 'other', 'dirty': False})
        self.voices.write_text(json.dumps({'NARRATOR': {'type': 'custom', 'seed': 99}}))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'inputs/code changed'):
            self.run_eval(renderer=lambda *args: None)

    def test_cancellation_preserves_completed_pairs_and_resumes_the_rest(self):
        flag = {'cancel': False}
        calls = []
        def renderer(row, voices, seeds, destination, cancel_check=None):
            calls.append(row['uid'])
            if row['uid'] == 'passage-001':
                raise ev.ContinuityEvaluationCancelled('fixture cancellation')
            return ev.dry_render_pair(row, voices, seeds, destination, cancel_check)
        first = self.run_eval(renderer=renderer, cancel_check=lambda: flag['cancel'])
        self.assertEqual('cancelled', first['status'])
        self.assertEqual([0], first['completed_rows'])
        self.assertEqual([1], first['missing_rows'])
        self.assertTrue((self.root / 'run/pairs/000_passage-000/attempt-1/state.json').is_file())
        incomplete = json.loads(
            (self.root / 'run/pairs/001_passage-001/attempt-1/state.json').read_text())
        self.assertEqual('incomplete', incomplete['status'])
        resumed = self.run_eval(renderer=ev.dry_render_pair)
        self.assertEqual('complete', resumed['status'])
        self.assertEqual([0, 1], resumed['completed_rows'])
        self.assertEqual(['passage-000', 'passage-001'], calls)
        self.assertEqual(2, json.loads(
            (self.root / 'run/pairs/001_passage-001/attempt-2/state.json').read_text())['attempt'])

    def test_invalid_audio_is_preserved_as_a_failed_attempt(self):
        def invalid(row, voices, seeds, destination, cancel_check=None):
            destination = Path(destination)
            for arm in ev.ARMS:
                path = destination / f'{arm}.wav'
                path.write_bytes(b'not a wav')
            return {arm: {'submitted_text': row[arm]['text'], 'path': f'{arm}.wav'}
                    for arm in ev.ARMS}
        failed = self.run_eval(rows=(0,), renderer=invalid)
        self.assertEqual('failed', failed['status'])
        state = json.loads((self.root / 'run/pairs/000_passage-000/attempt-1/state.json').read_text())
        self.assertEqual('failed', state['status'])
        self.assertTrue(state['reason'])
        resumed = self.run_eval(rows=(0,), renderer=ev.dry_render_pair)
        self.assertEqual('complete', resumed['status'])
        self.assertEqual('failed', json.loads(
            (self.root / 'run/pairs/000_passage-000/attempt-1/state.json').read_text())['status'])
        self.assertEqual(2, json.loads(
            (self.root / 'run/pairs/000_passage-000/attempt-2/state.json').read_text())['attempt'])

    def test_package_requires_complete_passing_run_and_separate_concealed_key(self):
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, '(not complete|manifest is missing)'):
            ev.build_blind_package(self.root / 'missing', self.root / 'pkg',
                                   self.root / 'public.json', self.root / 'key.json')
        def fail_second(row, voices, seeds, destination, cancel_check=None):
            if row['uid'] == 'passage-001':
                raise RuntimeError('fixture failure')
            return ev.dry_render_pair(row, voices, seeds, destination, cancel_check)
        self.run_eval(renderer=fail_second)
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'not complete'):
            ev.build_blind_package(self.root / 'run', self.root / 'pkg',
                                   self.root / 'public.json', self.root / 'key.json')
        self.run_eval(name='passed')
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'separate files'):
            ev.build_blind_package(self.root / 'passed', self.root / 'pkg2',
                                   self.root / 'same.json', self.root / 'same.json')
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'outside the package'):
            ev.build_blind_package(self.root / 'passed', self.root / 'pkg3',
                                   self.root / 'public3.json', self.root / 'pkg3/key.json')
        def identical(row, voices, seeds, destination, cancel_check=None):
            arms = ev.dry_render_pair(row, voices, seeds, destination, cancel_check)
            (Path(destination) / 'deterministic.wav').write_bytes(
                (Path(destination) / 'baseline.wav').read_bytes())
            return arms
        same = self.run_eval(name='same', rows=(0,), renderer=identical)
        self.assertEqual('failed', same['status'])

    def test_submitted_text_difference_is_a_separate_fidelity_failure(self):
        def altered(row, voices, seeds, destination, cancel_check=None):
            arms = ev.dry_render_pair(row, voices, seeds, destination, cancel_check)
            arms['deterministic']['submitted_text'] += '.'
            return arms
        result = self.run_eval(rows=(0,), renderer=altered)
        self.assertEqual('complete', result['status'])
        self.assertEqual('failed', result['results']['input_fidelity']['status'])
        self.assertEqual([{'row_index': 0, 'arm': 'deterministic'}],
                         result['results']['input_fidelity']['failed_arms'])
        self.assertEqual('not_provided', result['results']['content_verification']['status'])
        self.assertEqual('not_provided', result['results']['voice_scoring']['status'])

    def test_blind_package_and_answers_keep_categories_and_report_missing(self):
        self.run_eval()
        public, key = ev.build_blind_package(self.root / 'run', self.root / 'package',
                                             self.root / 'public.json', self.root / 'key.json')
        self.assertEqual(2, len(public['sets']))
        self.assertEqual(4, sum(len(item['samples']) for item in public['sets']))
        self.assertNotIn('deterministic', json.dumps(public))
        self.assertEqual(public['concealed_key_sha256'],
                         ev.file_sha256(self.root / 'key.json'))
        self.assertEqual({'baseline', 'deterministic'},
                         {entry['arm'] for item in key['sets'] for entry in item['mapping'].values()})
        answers = self.root / 'answers.json'
        answers.write_text(json.dumps({'concealed_key_sha256': public['concealed_key_sha256'],
            'listeners': [{'id': 'L1', 'answers': [
            {'set_id': 'pair_000', 'preference': 'tie'}]}]}))
        partial = ev.import_answers(self.root / 'package', self.root / 'public.json',
                                    self.root / 'key.json', answers)
        self.assertEqual('incomplete', partial['status'])
        self.assertEqual([{'listener': 'L1', 'set_id': 'pair_001'}],
                         partial['human_preference']['missing'])
        self.assertEqual('passed', partial['input_fidelity']['status'])
        self.assertEqual('not_provided', partial['content_verification']['status'])
        self.assertEqual('not_provided', partial['voice_scoring']['status'])
        samples = public['sets'][0]['samples']
        answers.write_text(json.dumps({'concealed_key_sha256': public['concealed_key_sha256'],
            'listeners': [{'id': 'L1', 'answers': [
            {'set_id': 'pair_000', 'preference': samples[0]['file'],
             'voice_scores': {samples[0]['file']: 2, samples[1]['file']: 4}},
            {'set_id': 'pair_001', 'preference': 'tie'}]}]}))
        complete = ev.import_answers(self.root / 'package', self.root / 'public.json',
                                     self.root / 'key.json', answers)
        self.assertEqual('complete', complete['status'])
        self.assertEqual(2, complete['voice_scoring']['scores'])
        self.assertEqual(2, len(complete['voice_scoring']['values']))
        self.assertEqual([2, 4], sorted(item['score'] for item in complete['voice_scoring']['values']))
        self.assertEqual({'L1'}, {item['listener'] for item in complete['voice_scoring']['values']})
        self.assertEqual({'baseline', 'deterministic'},
                         {item['arm'] for item in complete['voice_scoring']['values']})
        self.assertEqual(2, sum(complete['human_preference']['counts'].values()))
        mapping = {item['id']: item for item in key['sets']}['pair_000']['mapping']
        chosen = mapping[samples[0]['file']]['arm']
        self.assertEqual(1, complete['human_preference']['counts'][chosen])

    def test_fidelity_failure_cannot_be_packaged_and_package_audio_tamper_is_detected(self):
        def altered(row, voices, seeds, destination, cancel_check=None):
            arms = ev.dry_render_pair(row, voices, seeds, destination, cancel_check)
            arms['deterministic']['submitted_text'] += '.'
            return arms
        self.run_eval(name='altered', rows=(0,), renderer=altered)
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'input-fidelity'):
            ev.build_blind_package(self.root / 'altered', self.root / 'pkg-altered',
                                   self.root / 'public-altered.json', self.root / 'key-altered.json')
        self.run_eval(name='tamper', rows=(0,))
        public, _ = ev.build_blind_package(self.root / 'tamper', self.root / 'pkg',
                                           self.root / 'public.json', self.root / 'key.json')
        sample = self.root / 'pkg' / public['sets'][0]['samples'][0]['file']
        sample.write_bytes(sample.read_bytes()[:-2])
        answers = self.root / 'answers.json'
        answers.write_text(json.dumps({'concealed_key_sha256': public['concealed_key_sha256'],
            'listeners': [{'id': 'L1', 'answers': [
            {'set_id': 'pair_000', 'preference': 'tie'}]}]}))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'packaged audio (changed|is invalid)'):
            ev.import_answers(self.root / 'pkg', self.root / 'public.json',
                              self.root / 'key.json', answers)

    def test_package_tamper_and_duplicate_answers_are_rejected(self):
        self.run_eval()
        public, key = ev.build_blind_package(self.root / 'run', self.root / 'package',
                                             self.root / 'public.json', self.root / 'key.json')
        bad = self.root / 'bad.json'
        bad.write_text(json.dumps({'concealed_key_sha256': public['concealed_key_sha256'],
            'listeners': [{'id': 'L1', 'answers': [
            {'set_id': 'pair_000', 'preference': 'tie'},
            {'set_id': 'pair_000', 'preference': 'tie'}]}]}))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'duplicate answer'):
            ev.import_answers(self.root / 'package', self.root / 'public.json',
                              self.root / 'key.json', bad)
        key_path = self.root / 'key.json'
        key_path.write_text(key_path.read_text() + ' ')
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'concealed key changed'):
            ev.import_answers(self.root / 'package', self.root / 'public.json',
                              key_path, bad)


    def test_packaging_recomputes_fidelity_and_refuses_stale_pass(self):
        self.run_eval()
        state_path = next((self.root / 'run/pairs').glob('000_*/attempt-1/state.json'))
        state = json.loads(state_path.read_text())
        state['arms']['deterministic']['submitted_text'] += '.'
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'input-fidelity'):
            ev.build_blind_package(self.root / 'run', self.root / 'stale-package',
                                   self.root / 'stale-public.json', self.root / 'stale-key.json')

    def test_packaging_rejects_a_consistent_request_tamper(self):
        self.run_eval()
        state_path = next((self.root / 'run/pairs').glob('000_*/attempt-1/state.json'))
        state = json.loads(state_path.read_text())
        state['arms']['deterministic']['submitted_text'] += '.'
        state['requested']['deterministic']['text'] = state['arms']['deterministic']['submitted_text']
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'saved request differs from the plan'):
            ev.build_blind_package(self.root / 'run', self.root / 'consistent-package',
                                   self.root / 'consistent-public.json', self.root / 'consistent-key.json')

    def test_packaging_rejects_a_restored_submitted_text(self):
        def altered(row, voices, seeds, destination, cancel_check=None):
            arms = ev.dry_render_pair(row, voices, seeds, destination, cancel_check)
            arms['deterministic']['submitted_text'] += '.'
            return arms
        self.run_eval(name='restored', rows=(0,), renderer=altered)
        state_path = next((self.root / 'restored/pairs').glob('000_*/attempt-1/state.json'))
        state = json.loads(state_path.read_text())
        state['arms']['deterministic']['submitted_text'] = state['requested']['deterministic']['text']
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'fidelity evidence changed'):
            ev.build_blind_package(self.root / 'restored', self.root / 'restored-package',
                                   self.root / 'restored-public.json', self.root / 'restored-key.json')

    def test_packaging_refuses_manifest_that_omits_a_failed_pair(self):
        def fail_second(row, voices, seeds, destination, cancel_check=None):
            if row['uid'] == 'passage-001':
                raise RuntimeError('fixture failure')
            return ev.dry_render_pair(row, voices, seeds, destination, cancel_check)
        self.run_eval(renderer=fail_second)
        run_path = self.root / 'run' / 'run.json'
        run = json.loads(run_path.read_text())
        run['status'] = 'complete'
        run['missing_rows'] = []
        run['results']['input_fidelity'] = {'status': 'passed', 'checked_arms': 2, 'failed_arms': []}
        run_path.write_text(json.dumps(run))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'missing a completed pair'):
            ev.build_blind_package(self.root / 'run', self.root / 'omitted-package',
                                   self.root / 'omitted-public.json', self.root / 'omitted-key.json')

    def test_packaging_collision_preserves_foreign_output_directory(self):
        self.run_eval()
        package = self.root / 'collision-package'
        real_move = ev.move_source_upload_exclusively
        def collide(source, destination):
            if Path(destination) == package:
                package.mkdir()
                (package / 'foreign.txt').write_text('foreign')
            return real_move(source, destination)
        with patch.object(ev, 'move_source_upload_exclusively', side_effect=collide):
            with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'refusing to overwrite'):
                ev.build_blind_package(self.root / 'run', package, self.root / 'collision-public.json',
                                       self.root / 'collision-key.json')
        self.assertEqual('foreign', (package / 'foreign.txt').read_text())
        (package / 'foreign.txt').unlink()
        package.rmdir()
        def collide_empty(source, destination):
            if Path(destination) == package:
                package.mkdir()
            return real_move(source, destination)
        with patch.object(ev, 'move_source_upload_exclusively', side_effect=collide_empty):
            with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'refusing to overwrite'):
                ev.build_blind_package(self.root / 'run', package, self.root / 'collision-public.json',
                                       self.root / 'collision-key.json')
        self.assertTrue(package.is_dir())
        self.assertEqual([], list(package.iterdir()))

    def test_directory_cleanup_does_not_delete_a_replacement(self):
        path = self.root / 'staging'
        path.mkdir()
        (path / 'owned.txt').write_text('owned')
        identity = ev._path_identity(path)
        real_clear = ev._clear_directory_fd
        def swap(fd):
            path.rename(self.root / 'moved-owned')
            path.mkdir()
            (path / 'foreign.txt').write_text('foreign')
            return real_clear(fd)
        with patch.object(ev, '_clear_directory_fd', side_effect=swap):
            ev._remove_owned_dir(path, identity)
        self.assertEqual('foreign', (path / 'foreign.txt').read_text())
        self.assertFalse((self.root / 'moved-owned' / 'owned.txt').exists())

    def test_owned_directory_cleanup_removes_contents(self):
        path = self.root / 'owned-staging'
        path.mkdir()
        (path / 'owned.txt').write_text('owned')
        ev._remove_owned_dir(path, ev._path_identity(path))
        self.assertFalse((path / 'owned.txt').exists())

    def test_packaging_collision_preserves_foreign_public_file(self):
        self.run_eval()
        public = self.root / 'collision-public.json'
        real_move = ev.move_source_upload_exclusively
        def collide(source, destination):
            if Path(destination) == public:
                public.write_text('foreign')
            return real_move(source, destination)
        with patch.object(ev, 'move_source_upload_exclusively', side_effect=collide):
            with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'refusing to overwrite'):
                ev.build_blind_package(self.root / 'run', self.root / 'public-collision-package',
                                       public, self.root / 'public-collision-key.json')
        self.assertEqual('foreign', public.read_text())

    def test_answers_are_bound_to_one_package_randomization(self):
        self.run_eval()
        public_a, _ = ev.build_blind_package(self.root / 'run', self.root / 'package-a',
                                             self.root / 'public-a.json', self.root / 'key-a.json', seed=1258)
        public_b, _ = ev.build_blind_package(self.root / 'run', self.root / 'package-b',
                                             self.root / 'public-b.json', self.root / 'key-b.json', seed=999)
        self.assertNotEqual(public_a['concealed_key_sha256'], public_b['concealed_key_sha256'])
        choice = public_a['sets'][0]['samples'][0]['file']
        answers = self.root / 'answers.json'
        answers.write_text(json.dumps({'concealed_key_sha256': public_a['concealed_key_sha256'],
            'listeners': [{'id': 'L1', 'answers': [
                {'set_id': 'pair_000', 'preference': choice}]}]}))
        ev.import_answers(self.root / 'package-a', self.root / 'public-a.json',
                          self.root / 'key-a.json', answers)
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'different package'):
            ev.import_answers(self.root / 'package-b', self.root / 'public-b.json',
                              self.root / 'key-b.json', answers)
        answers.write_text(json.dumps({'listeners': [{'id': 'L1', 'answers': [
            {'set_id': 'pair_000', 'preference': choice}]}]}))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'different package'):
            ev.import_answers(self.root / 'package-a', self.root / 'public-a.json',
                              self.root / 'key-a.json', answers)

    def test_failed_collection_exits_nonzero(self):
        failed = {'status': 'failed', 'completed_rows': [], 'missing_rows': [0], 'results': {}}
        with patch.object(ev, 'run_collection', return_value=failed):
            code = ev.main(['run', '--source', str(SOURCE), '--voices', str(self.voices),
                            '--config', str(self.config), '--out', str(self.root / 'cli'),
                            '--rows', '0', '--dry-run'])
        self.assertEqual(1, code)


    def test_default_packages_use_independent_randomization(self):
        self.run_eval()
        public_a, _ = ev.build_blind_package(self.root / 'run', self.root / 'random-a',
                                             self.root / 'random-a.json', self.root / 'random-a-key.json')
        public_b, _ = ev.build_blind_package(self.root / 'run', self.root / 'random-b',
                                             self.root / 'random-b.json', self.root / 'random-b-key.json')
        self.assertNotEqual(public_a['concealed_key_sha256'], public_b['concealed_key_sha256'])

    def test_package_cli_default_seed_is_random(self):
        self.run_eval()
        keys = []
        for name in ('cli-random-a', 'cli-random-b'):
            code = ev.main(['package', '--run', str(self.root / 'run'),
                            '--package-dir', str(self.root / name),
                            '--out', str(self.root / (name + '.json')),
                            '--key', str(self.root / (name + '-key.json'))])
            self.assertEqual(0, code)
            keys.append(ev.file_sha256(self.root / (name + '-key.json')))
        self.assertNotEqual(keys[0], keys[1])

    def test_complete_run_is_not_marked_cancelled_by_an_immediate_cancel(self):
        self.run_eval()
        resumed = self.run_eval(cancel_check=lambda: True)
        self.assertEqual('complete', resumed['status'])
        self.assertEqual([0, 1], resumed['completed_rows'])

    def test_fidelity_failure_exits_nonzero_even_when_pairs_complete(self):
        complete_but_failed = {'status': 'complete', 'completed_rows': [0], 'missing_rows': [],
            'results': {'input_fidelity': {'status': 'failed'}}}
        with patch.object(ev, 'run_collection', return_value=complete_but_failed):
            code = ev.main(['run', '--source', str(SOURCE), '--voices', str(self.voices),
                            '--config', str(self.config), '--out', str(self.root / 'cli-fidelity'),
                            '--rows', '0', '--dry-run'])
        self.assertEqual(1, code)

    def test_packaging_rejects_a_pair_state_from_another_row(self):
        self.run_eval()
        run_path = self.root / 'run' / 'run.json'
        run = json.loads(run_path.read_text())
        first = next(item for item in run['pairs'] if item['row_index'] == 0)
        for item in run['pairs']:
            if item['row_index'] == 1:
                item['path'] = first['path']
        run_path.write_text(json.dumps(run))
        with self.assertRaisesRegex(ev.ContinuityEvaluationError, 'row identity'):
            ev.build_blind_package(self.root / 'run', self.root / 'aliased-package',
                                   self.root / 'aliased-public.json', self.root / 'aliased-key.json')


if __name__ == '__main__':
    unittest.main()

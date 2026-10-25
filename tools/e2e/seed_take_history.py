"""Seed one private synthetic book with a saved, evidence-backed take.

Run with the app interpreter from ``app/``. This is E2E fixture setup only: it
uses the existing CPU fixture renderer and take-history code, never a model or
GPU. The target must be an existing empty absolute directory.
"""
import copy
import json
import os
from pathlib import Path
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "app")
sys.path.insert(0, APP)

import numpy as np
import soundfile as sf
from project import ProjectManager
from book_state_transaction import ensure_book_state
from take_retention import get_take_history_policy, set_take_history_policy
from tests.test_take_restoration import TakeRestorationTests


def main(data_dir):
    target = Path(data_dir)
    if (not os.path.isabs(data_dir) or target.is_symlink()
            or not target.is_dir() or any(target.iterdir())):
        raise ValueError('E2E seeding requires an existing empty absolute directory')
    (target / 'state.json').write_text(json.dumps({
        'active_book_id': 'e2e-take-history', 'book_generation': 'one'}))
    (target / 'voicelines').mkdir()
    manager = ProjectManager(str(target))
    prior = target / 'voicelines/prior.wav'
    fresh = target / 'voicelines/fresh.wav'
    sf.write(prior, np.full(2400, .1), 24000, subtype='PCM_16')
    sf.write(fresh, np.sin(np.arange(2400) * .1) * .2, 24000, subtype='PCM_16')
    # Both files are only fallbacks; the fixture publishes real synthetic PCM
    # and records the origin as the saved snapshot.
    manager.save_chunks([dict(id=0, uid='line', text='Original synthetic words.',
        speaker='NARRATOR', instruct='', take=2, status='done',
        audio_path='voicelines/prior.wav', audio_revision='original-revision')])
    case = TakeRestorationTests()
    with case.owner():
        engine = case.engine()
        (target / 'config.json').write_text(json.dumps({'tts': {
            **engine.get_model_settings(), 'synthesis_recovery': engine._synthesis_recovery}}))
        manager.invalidate_config_cache()
        (target / 'voice_config.json').write_text(json.dumps(
            {'NARRATOR': {'type': 'custom', 'voice': 'Ryan', 'seed': 42}}))
        with ensure_book_state(str(target)):
            set_take_history_policy(manager, True,
                                    get_take_history_policy(str(target))['revision'])
        chunk = manager.load_chunks()[0]
        parent, admitted = case.admission(manager, engine, chunk)
        pcm, _, synthesis, observed = case.render(target, engine, parent, chunk)
        manager._publish_generated_chunk_audio(
            {**chunk, '_synthesis_receipt': synthesis, '_speech_input': observed},
            str(pcm), 'NARRATOR', recovery_parent=parent, publication_admission=admitted)
        origin = copy.deepcopy(manager.load_chunks()[0])
        original = (target / origin['audio_path']).read_bytes()
        manager.update_chunk(0, {'take': 3})
        manager._publish_generated_chunk_audio(manager.load_chunks()[0], str(fresh), 'NARRATOR')
        current = copy.deepcopy(manager.load_chunks()[0])
        displaced = (target / current['audio_path']).read_bytes()
        if original == displaced:
            raise RuntimeError('fixture produced identical origin and displaced audio')
        # A second selectable row exercises pending-action row ownership.
        rows = [
            current,
            dict(id=1, uid='other', text='Second synthetic words.', speaker='NARRATOR',
                 instruct='', take=0, status='done', audio_path='voicelines/fresh.wav',
                 audio_revision='other-revision'),
        ]
        manager.save_chunks(rows)
        (target / 'annotated_script.json').write_text(json.dumps([
            {'speaker': row['speaker'], 'text': row['text'], 'instruct': ''}
            for row in rows]))
        from audio_take_history import AudioTakeHistory
        archives = AudioTakeHistory(str(target)).list()
        snapshots = [row for row in archives['records'] if row['has_restore_evidence']]
        if not snapshots:
            raise RuntimeError('fixture did not retain restore evidence')
        output = {'rows': 2, 'snapshot_version': snapshots[0]['version'],
                  'snapshot_sha256': snapshots[0]['sha256'],
                  'original_sha256': __import__('hashlib').sha256(original).hexdigest(),
                  'current_sha256': __import__('hashlib').sha256(displaced).hexdigest()}
        print(json.dumps(output))


if __name__ == '__main__':
    main(os.environ['ALEXANDRIA_DATA_DIR'])

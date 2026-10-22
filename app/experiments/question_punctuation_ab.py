"""Owned synthetic question / historical question-period comparison (#1519).

#1518 fixed authored-question preparation. The ?. arm deliberately recreates
that historical perturbation; both arms use the prepared-text leaf. Actual
submitted text and artifact hashes must match before a clip is recorded.

Run in a fresh process with explicit local settings, absolute LoRA adapter
paths, nonnegative seeds, synthesis windows disabled and a NEW output folder
outside the checkout. Runs are not resumed: changed inputs must never reuse
one arm of an older pair. Partial runs remain labelled incomplete.

This captures controlled inputs, not a validated pitch effect or listening
result. The paper studied other models; its findings are not proof for Qwen.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from fastapi import HTTPException

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import atomic_json_write
from adapter_publication import save_adapter_publication_bytes
from experiments.provenance import file_sha256, provenance
from experiments.run_dialogue_continuity import (_get_input,
    get_continuity_output_path, get_experiment_source_identity, run_owned_audio_experiment)
from synthesis_settings import get_enabled_synthesis_window_settings

# (id, words without terminal mark, question type)
LINES = [
    ("yn01", "Will you wait for me by the old stone gate", "yes_no"),
    ("yn02", "Did the baker leave the lantern on all night", "yes_no"),
    ("yn03", "Is that really the road to the harbor", "yes_no"),
    ("yn04", "Can we finish the map before the rain comes", "yes_no"),
    ("yn05", "Have you ever seen the river this low", "yes_no"),
    ("yn06", "Are they still waiting in the garden", "yes_no"),
    ("wh01", "Where did you put the brass key", "wh"),
    ("wh02", "Why would anyone climb the tower at night", "wh"),
    ("wh03", "Who told you about the hidden door", "wh"),
    ("wh04", "What are we supposed to do with the boat", "wh"),
]
ARMS = {"question": "?", "question_period": "?."}


def get_voice_entries(raw, speakers):
    from tts import voice_category

    if not isinstance(raw, dict):
        raise ValueError("Voice configuration must be an object")
    config = raw.get("characters") if isinstance(raw.get("characters"), dict) else raw
    entries = {}
    for speaker in speakers:
        entry = config.get(speaker)
        if not isinstance(entry, dict) or voice_category(entry) != "lora":
            raise ValueError(f"{speaker!r} is not a LoRA voice")
        path = entry.get("adapter_path")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError("Declare an absolute adapter_path for each experiment voice")
        entries[speaker] = copy.deepcopy(entry)
    return entries


def get_question_inputs(args):
    voices_raw, config_raw = map(_get_input, (args.voice_config, args.config))
    voices, config = json.loads(voices_raw), json.loads(config_raw)
    speakers = [s.strip() for s in args.speakers.split(",") if s.strip()]
    seeds = [int(s) for s in args.seeds.split(",")]
    if not speakers or len(speakers) != len(set(speakers)):
        raise ValueError("Choose nonempty, unique speakers")
    if not seeds or len(seeds) != len(set(seeds)) or any(not 0 <= seed < 2**31 for seed in seeds):
        raise ValueError("Choose unique explicit seeds from 0 through 2147483647")
    if not 0 <= args.limit <= len(LINES):
        raise ValueError("limit must be between zero and the number of fixture lines")
    if not isinstance(config, dict) or not isinstance(config.get("tts"), dict) or config['tts'].get('mode') != 'local':
        raise ValueError("This experiment requires explicit local TTS settings")
    if get_enabled_synthesis_window_settings(config['tts'].get('synthesis_windows')) is not None:
        raise ValueError("Disable synthesis windows for the single-request punctuation comparison")
    entries = get_voice_entries(voices, speakers)
    return config_raw, voices_raw, entries, seeds, LINES[:args.limit] if args.limit else LINES


def freeze_question_voices(entries):
    from adapter_checkpoint_transaction import ensure_adapter_generation_snapshot
    from audio_generation_owner import get_audio_generation_claim_id
    from voice_manifest import get_resolved_adapter_path

    if get_audio_generation_claim_id() is None:
        raise ValueError("Question rendering requires an owned audio task")
    frozen = {}
    for speaker, entry in entries.items():
        path = get_resolved_adapter_path(entry['adapter_path'])
        with ensure_adapter_generation_snapshot(path) as (_snapshot, generation):
            expected = entry.get('adapter_generation_sha256')
            if expected is not None and expected != generation:
                raise ValueError("Adapter changed since experiment input admission")
            frozen[speaker] = {**entry, 'adapter_path': path, 'adapter_generation_sha256': generation}
    return frozen


def render_exact(engine, text, voice, path):
    """Owned prepared-text submission; fresh artifacts only, with observed proof."""
    from audio_generation_owner import ensure_audio_generation_active, get_audio_generation_claim_id
    from audio_validation import validate_generated_audio
    from synthesis_input import ensure_speech_input_capture, get_captured_speech_input

    if get_audio_generation_claim_id() is None:
        raise ValueError("Question rendering requires an owned audio task")
    ensure_audio_generation_active()
    if os.path.lexists(path):
        raise FileExistsError("Question output already exists; choose a fresh run")
    with ensure_speech_input_capture():
        if engine._generate_lora_voice_prepared(text, "", copy.deepcopy(voice), str(path)) is not True:
            raise RuntimeError("Question generation did not finish")
        ensure_audio_generation_active()
        validate_generated_audio(str(path), "question punctuation A/B")
        observed = get_captured_speech_input(str(path))
        if (not isinstance(observed, dict) or observed.get('text') != text
                or observed.get('provenance') != 'local_lora_api'
                or observed.get('audio', {}).get('sha256') != file_sha256(path)):
            raise ValueError("Question clip lacks matching actual submitted-input evidence")
        ensure_audio_generation_active()
        return observed


def render_question_pairs(engine, entries, seeds, lines, out, identity):
    from audio_generation_owner import ensure_audio_generation_active, ensure_audio_generation_publication

    settings = copy.deepcopy(engine.get_model_settings())
    if settings.get('mode') != 'local' or get_enabled_synthesis_window_settings(settings.get('synthesis_windows')) is not None:
        raise ValueError("The admitted engine must be local with synthesis windows disabled")
    entries = freeze_question_voices(entries)
    rows = []
    for line_id, words, kind in lines:
        for speaker, entry in entries.items():
            # Speaker labels remain metadata, never filesystem path components.
            speaker_id = hashlib.sha256(speaker.encode('utf-8')).hexdigest()
            for seed in seeds:
                for arm, mark in ARMS.items():
                    ensure_audio_generation_active()
                    if engine.get_model_settings() != settings:
                        raise ValueError("Engine settings changed during the comparison")
                    clip_id = f"{line_id}_{speaker_id}_{seed}_{arm}"
                    wav = out / 'wav' / (clip_id + '.wav')
                    if wav.resolve().parent != (out / 'wav').resolve():
                        raise ValueError("Question output escaped its run directory")
                    submitted = words + mark
                    observed = render_exact(engine, submitted, dict(entry, seed=str(seed)), wav)
                    if engine.get_model_settings() != settings:
                        raise ValueError("Engine settings changed during rendering")
                    rows.append({'clip_id': clip_id, 'line_id': line_id, 'question_type': kind,
                        'speaker': speaker, 'adapter_id': entry.get('adapter_id'),
                        'adapter_generation_sha256': entry['adapter_generation_sha256'],
                        'seed': seed, 'arm': arm, 'requested_text': submitted,
                        'submitted_text': observed['text'], 'speech_input': observed,
                        'wav': str(wav), 'wav_sha256': observed['audio']['sha256']})
                    atomic_json_write({'status': 'incomplete', 'identity': identity, 'provenance': identity['provenance'],
                        'model_settings': settings, 'rows': rows}, str(out / 'rows.json'))
    document = {'status': 'captured', 'identity': identity, 'provenance': identity['provenance'], 'model_settings': settings, 'rows': rows,
                'qualification': 'exact submitted inputs captured; pitch/listening effect unvalidated'}
    manifest = ''.join(json.dumps({'id': row['clip_id'], 'wav': row['wav'],
        'text': row['submitted_text'], 'wav_sha256': row['wav_sha256']}) + '\n' for row in rows)
    with ensure_audio_generation_publication():
        if os.path.lexists(out / 'manifest.jsonl'):
            raise FileExistsError('Question manifest already exists')
        save_adapter_publication_bytes(str(out / 'manifest.jsonl'), manifest.encode('utf-8'))
        atomic_json_write(document, str(out / 'rows.json'))
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice-config', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--speakers', default='NARRATOR,EMILIA')
    parser.add_argument('--seeds', default='1234')
    parser.add_argument('--limit', type=int, default=0, help='0 = all synthetic lines')
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args(argv)
    try:
        if 'core' in sys.modules or os.environ.get('ALEXANDRIA_DATA_DIR'):
            raise ValueError('Run in a fresh process without a data directory override')
        config_raw, voices_raw, entries, seeds, lines = get_question_inputs(args)
        root = Path(REPO).resolve()
        identity = {**get_experiment_source_identity(root), 'config_sha256': hashlib.sha256(config_raw).hexdigest(),
                    'voices_sha256': hashlib.sha256(voices_raw).hexdigest(), 'provenance': provenance(__file__, args)}
        out = get_continuity_output_path(root, args.out_dir)
        out.mkdir(mode=0o700, exist_ok=False)
        (out / 'wav').mkdir(); data = out / 'data'; data.mkdir()
        (data / 'config.json').write_bytes(config_raw)
        atomic_json_write({'status': 'incomplete', 'identity': identity, 'provenance': identity['provenance'], 'rows': []}, str(out / 'rows.json'))
        os.environ['ALEXANDRIA_DATA_DIR'] = str(data)
        import core
        document = run_owned_audio_experiment(core, lambda engine: render_question_pairs(
            engine, entries, seeds, lines, out, identity), out / 'run')
        if get_experiment_source_identity(root) != {key: identity[key] for key in ('head', 'tree')}:
            raise ValueError('Experiment source changed during rendering')
    except (OSError, ValueError, RuntimeError, HTTPException) as error:
        parser.error(str(error))
    print(json.dumps({'status': document['status'], 'clips': len(document['rows']), 'out': str(out),
                      'qualification': document['qualification']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

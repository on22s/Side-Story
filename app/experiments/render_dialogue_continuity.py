"""Owned baseline/deterministic pair capture; no audible qualification implied.

The controller must hold AA2's audio task and supply its engine and frozen voice
configuration. Each destination is new; this module never reuses saved takes.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from adapter_publication import save_adapter_publication_bytes
from audio_generation_owner import (ensure_audio_generation_active,
    ensure_audio_generation_publication, get_audio_generation_claim_id)
from audio_validation import GeneratedAudioError, validate_generated_audio
from experiments.plan_dialogue_continuity import get_continuity_experiment_packet
from project_scope_files import capture_scope_file
from synthesis_recovery_identity import get_recovery_digest
from utils import file_lock
from word_timing import MAX_AUDIO_BYTES

HIDDEN_CONTEXT_WORDS = 5
MAX_HIDDEN_CONTEXT_CHARS = 256


def get_hidden_context_capture_requests(packet, row_index):
    """Plan raw context captures; these offsets never authorize audio cropping."""
    rows = packet['plan']['rows']
    if type(row_index) is not int or not 0 < row_index < len(rows) - 1:
        raise ValueError('Hidden context requires a row with both neighboring rows')

    def context(text, preceding=False):
        words = list(re.finditer(r'\S+', text))
        selected = words[-HIDDEN_CONTEXT_WORDS:] if preceding else words[:HIDDEN_CONTEXT_WORDS]
        value = text[selected[0].start():selected[-1].end()] if selected else ''
        if not value or len(value) > MAX_HIDDEN_CONTEXT_CHARS:
            raise ValueError('Hidden context must contain at most 256 characters')
        return value, [selected[0].start(), selected[-1].end()]

    row = rows[row_index]
    authored = row['baseline']['text']
    preceding, preceding_span = context(rows[row_index - 1]['baseline']['text'], preceding=True)
    following, following_span = context(rows[row_index + 1]['baseline']['text'])
    requests = {}
    for arm, before in (('hidden_following', ''), ('hidden_sandwich', preceding)):
        prefix = before + ' ' if before else ''
        text = prefix + authored + ' ' + following
        span = [len(prefix), len(prefix) + len(authored)]
        contract = {'version': 1, 'preceding': before, 'following': following,
                    'authored_text': authored, 'authored_span_in_request': span,
                    'coordinate_space': 'requested_text_only',
                    'offset_unit': 'unicode_code_points', 'separator': ' ',
                    'word_limit': HIDDEN_CONTEXT_WORDS,
                    'pause_after_application': 'not_applied_to_raw_audio'}
        request = {**copy.deepcopy(row['baseline']), 'text': text,
                   'hidden_context': contract}
        following_start = span[1] + 1
        request['context_provenance'] = {
            'preceding': ({'row_index': row_index - 1, 'uid': rows[row_index - 1]['uid'],
                'speaker': rows[row_index - 1]['speaker'], 'source_span': preceding_span,
                'request_span': [0, len(before)]} if before else None),
            'following': {'row_index': row_index + 1, 'uid': rows[row_index + 1]['uid'],
                'speaker': rows[row_index + 1]['speaker'], 'source_span': following_span,
                'request_span': [following_start, len(text)]}}
        request['context_contract_sha256'] = get_recovery_digest({
            'speaker': row['speaker'], 'instruct': request['instruct'],
            'pause_after': request['pause_after'], 'contract': contract})
        requests[arm] = request
    return requests


def get_continuity_voice_inputs(voice_config, speaker, row_index):
    """Materialize the same selected mapping that both renders will receive."""
    from tts import (get_chunk_voice_inputs, get_resolved_speaker,
                     resolve_narrator_voice_config, voice_config_for_chunk)
    if not isinstance(voice_config, dict):
        raise ValueError('Continuity voices must be an object')
    voices = copy.deepcopy(voice_config)
    voices = voice_config_for_chunk(voices, speaker, row_index)
    resolved = get_resolved_speaker(speaker, voices)
    voices = voice_config_for_chunk(resolve_narrator_voice_config(resolved, voices), resolved, row_index)
    inputs = get_chunk_voice_inputs(voices, {'speaker': resolved}, row_index)
    seeds = {name: entry['seed'] for name, entry in inputs.items() if entry['type'] != 'ensemble'}
    if not seeds or any(type(seed) is not int or not 0 <= seed < 2**31 for seed in seeds.values()):
        raise ValueError('Continuity requires an explicit nonnegative seed for every effective voice')
    return voices, inputs, seeds


def save_continuity_render_pair(engine, raw_source, packet, row_index, voice_config, destination):
    """Render exactly two arms, publishing a complete new pair or nothing.

    The receipt captures requested and actually submitted text separately.
    Native serving/model identity, alignment, memory, drift and listening are
    still controller qualification responsibilities, never inferred here.
    """
    return _save_continuity_capture(engine, raw_source, packet, row_index,
                                    voice_config, destination, hidden_context=False)


def save_hidden_context_capture_pair(engine, raw_source, packet, row_index, voice_config, destination):
    """Capture two complete context requests, retaining actual submitted input.

    The WAVs include hidden speech and must not be delivered as authored takes.
    Request offsets are usable in submitted text only on an exact text match;
    preparation differences remain unresolved, never guessed or certified.
    """
    return _save_continuity_capture(engine, raw_source, packet, row_index,
                                    voice_config, destination, hidden_context=True)


def _save_continuity_capture(engine, raw_source, packet, row_index, voice_config, destination,
                             *, hidden_context):
    if get_audio_generation_claim_id() is None:
        raise ValueError('Continuity rendering requires an owned audio task')
    ensure_audio_generation_active()
    expected = get_continuity_experiment_packet(raw_source)
    if packet != expected:
        raise ValueError('Continuity source or loaded planner changed')
    rows = expected['plan']['rows']
    if type(row_index) is not int or not 0 <= row_index < len(rows):
        raise ValueError('Invalid continuity row index')
    row = rows[row_index]
    requests = (get_hidden_context_capture_requests(expected, row_index) if hidden_context else
                {arm: row[arm] for arm in ('baseline', 'deterministic')})
    voices, voice_inputs, seeds = get_continuity_voice_inputs(voice_config, row['speaker'], row_index)
    # Validate serializability before inference; identity does not authorize reuse.
    voice_digest = get_recovery_digest(voices)
    destination = Path(destination)
    with file_lock(str(destination)):
        if os.path.lexists(destination):
            raise FileExistsError('Choose a new continuity pair destination')
        with tempfile.TemporaryDirectory(prefix='.continuity-', dir=destination.parent) as stage:
            stage = Path(stage)
            arms = {}
            for arm, request in requests.items():
                ensure_audio_generation_active()
                path = stage / (arm + '.wav')
                started = time.monotonic()
                result = engine.generate_voice_result(request['text'], request['instruct'],
                    row['speaker'], copy.deepcopy(voices), str(path), capture_input=True)
                ensure_audio_generation_active()
                if not result.success:
                    raise GeneratedAudioError('Continuity arm generation failed')
                validate_generated_audio(str(path), 'continuity ' + arm)
                facts, _ = capture_scope_file(stage, path.name, limit=MAX_AUDIO_BYTES)
                audio = {'sha256': facts['sha256'], 'size': facts['size']}
                captured = result.speech_input
                if (not isinstance(captured, dict) or captured.get('audio') != audio
                        or not isinstance(captured.get('text'), str) or not captured['text']):
                    raise GeneratedAudioError('Continuity arm has no matching submitted-input capture')
                arms[arm] = {'request': copy.deepcopy(request), 'audio': audio,
                    'speech_input': copy.deepcopy(captured),
                    'synthesis_receipt': copy.deepcopy(result.synthesis_receipt),
                    'elapsed_seconds': time.monotonic() - started}
                if hidden_context:
                    exact = captured['text'] == request['text']
                    arms[arm]['submitted_request_match'] = exact
                    arms[arm]['authored_span_in_submitted'] = (
                        list(request['hidden_context']['authored_span_in_request']) if exact else None)
                    arms[arm]['submitted_span_status'] = (
                        'exact_request_observed' if exact else 'unresolved_preparation')
            receipt = {'version': 1, 'source_sha256': hashlib.sha256(raw_source).hexdigest(),
                'planner_loaded_code_sha256': expected['planner_loaded_code_sha256'],
                'row_index': row_index, 'uid': row['uid'], 'speaker': row['speaker'],
                'voice_config_digest': voice_digest, 'effective_voice_inputs': voice_inputs, 'seeds': seeds,
                'model_settings': engine.get_model_settings(), 'arms': arms,
                'qualification': 'captured_only; alignment, memory, drift and listening remain unqualified'}
            if hidden_context:
                receipt.update(version=2, kind='hidden_context_raw_capture',
                    qualification='raw_context_capture_only; includes hidden speech; cropping, '
                                  'authored phonemes, drift and listening remain unqualified')
            encoded = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2,
                                  allow_nan=False) + '\n').encode('utf-8')
            save_adapter_publication_bytes(str(stage / 'receipt.json'), encoded)
            with ensure_audio_generation_publication():
                if os.path.lexists(destination):
                    raise FileExistsError('Continuity pair destination appeared during rendering')
                os.rename(stage, destination)
            return receipt

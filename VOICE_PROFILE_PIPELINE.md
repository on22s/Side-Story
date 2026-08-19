# Real-reference voice profile pipeline

Alexandria treats source acquisition/separation as an offline curation stage. Chapter rendering only consumes immutable `voice_profile_id` values.

## Flow

1. Acquire a source that is authorised for the intended use and retain its URL/title.
2. Extract a lossless/high-bitrate audio track.
3. Separate music/effects from speech and remove overlapping speakers. This stage is deliberately pluggable: Mel-RoFormer/ClearerVoice/Demucs output can all feed the same preparation command.
4. Select one complete 6-15 second, single-speaker sentence. Avoid clipped speech, cut-off words, strong reverb, and residual music.
5. Transcribe the sentence exactly.
6. Prepare a canonical 24 kHz mono PCM16 WAV plus provenance manifest.
7. Publish it through `/voice_profiles/import` and bind the returned immutable Profile ID to a character.
8. Generate a preview before rerendering chapters. Use a new versioned ID when the reference changes.

## Commands

Inspect a separated candidate:

```bash
.venv/bin/python scripts/voice_profile.py inspect path/to/candidate.wav
```

Prepare a reference and manifest:

```bash
.venv/bin/python scripts/voice_profile.py prepare \
  --input path/to/separated.wav \
  --output references/animation/character/reference_neutral.wav \
  --speaker CHARACTER \
  --text 'Exact transcript' \
  --description 'Voice description' \
  --source-url 'https://source.example/video' \
  --source-title 'Source title' \
  --rights-basis 'Documented authorisation or licence' \
  --rights-confirmed
```

Publish and bind atomically from the operator's perspective (the local binding only happens after the remote import succeeds):

```bash
.venv/bin/python scripts/voice_profile.py publish \
  --manifest references/animation/character/reference_neutral.profile.json \
  --profile-id vp_character_neutral_v1 \
  --endpoint http://127.0.0.1:18000/tts \
  --book-dir books/fanren \
  --character CHARACTER
```

The server rejects missing rights metadata, references outside 3-30 seconds, near-empty audio, heavy clipping, excessive silence, transcript-free ICL cloning, and accidental replacement of an existing ID. `--force` is reserved for recovery; normal revisions use a new ID.

After changing a profile, existing rendered line WAVs remain cached. Use the normal render command with `--force` when intentionally regenerating old chapters.

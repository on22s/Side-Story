"""Does submitting an authored question as `?.` change how it ends? (#1516, #1519)

#1516: speech preparation appends `.` after authored terminal punctuation, so
"Will you wait?" reaches the model as "Will you wait?.". Vigneaux & Cole
(arXiv:2610.27403) found the final punctuation mark is the one prompt-side
lever that moves sentence-final intonation in staged TTS generators, the family
Qwen3-TTS belongs to. Whether `?.` costs us the rise has never been measured.

TWO ARMS, ONE VARIABLE. Every line is rendered twice with the same voice, seed
and words; only the terminal mark differs:

    question         "...?"   what the author wrote
    question_period  "...?."  what speech preparation submits today

BOTH ARMS BYPASS SPEECH PREPARATION ON PURPOSE. Every public TTSEngine entry
point runs `get_speech_preparation`, which would turn the `?` arm into `?.` as
well and leave nothing to compare. The prepared-text entry point is called
instead, and the exact string submitted is recorded beside each clip's hash, so
the artifact proves which text reached the model.

THE LINES ARE SYNTHETIC (Rule 27) and split by question type, because a
yes/no question is expected to rise in English and a wh-question usually falls.
The type is recorded, so a "fewer rises" result can be read per type.

Scoring is a separate CPU step: this writes a manifest that
`final_word_tune.py --manifest` reads. Resumable: an existing valid clip with
a recorded row is kept.
"""
import argparse
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(REPO, "app")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import atomic_json_write

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


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get_voice_entries(voice_config_path, speakers):
    raw = json.load(open(voice_config_path, encoding="utf-8"))
    config = raw.get("characters") if isinstance(raw.get("characters"), dict) else raw
    entries = {}
    for speaker in speakers:
        entry = config.get(speaker)
        if not isinstance(entry, dict) or entry.get("type") != "lora":
            raise SystemExit(f"{speaker!r} is not a LoRA voice in {voice_config_path}")
        entries[speaker] = entry
    return entries


def render_exact(engine, text, voice, path):
    """Render `text` exactly as given: no speech preparation."""
    from audio_validation import remove_stale_audio, validate_generated_audio

    remove_stale_audio(path)
    if engine._generate_lora_voice_prepared(text, "", voice, path) is False:
        raise RuntimeError(f"generation returned False for {text!r}")
    validate_generated_audio(path, "question punctuation A/B")


def main():
    from experiments.provenance import provenance

    parser = argparse.ArgumentParser()
    parser.add_argument("--voice-config", default=os.path.join(REPO, "voice_config.json"))
    parser.add_argument("--config", default=os.path.join(APP, "config.json"))
    parser.add_argument("--speakers", default="NARRATOR,EMILIA")
    parser.add_argument("--seeds", default="1234")
    parser.add_argument("--limit", type=int, default=0, help="0 = all lines")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    speakers = [s.strip() for s in args.speakers.split(",") if s.strip()]
    seeds = [int(s) for s in args.seeds.split(",")]
    lines = LINES[:args.limit] if args.limit else LINES
    entries = get_voice_entries(args.voice_config, speakers)
    os.makedirs(os.path.join(args.out_dir, "wav"), exist_ok=True)
    rows_path = os.path.join(args.out_dir, "rows.json")
    done = {}
    if os.path.exists(rows_path):
        done = {r["clip_id"]: r for r in json.load(open(rows_path, encoding="utf-8"))["rows"]}

    from tts import TTSEngine
    engine = TTSEngine(json.load(open(args.config, encoding="utf-8")))
    total = len(lines) * len(speakers) * len(seeds) * len(ARMS)
    for line_id, words, kind in lines:
        for speaker in speakers:
            for seed in seeds:
                for arm, mark in ARMS.items():
                    clip_id = f"{line_id}_{speaker}_{seed}_{arm}"
                    wav = os.path.join(args.out_dir, "wav", f"{clip_id}.wav")
                    if clip_id in done and os.path.exists(wav) \
                            and file_sha256(wav) == done[clip_id]["wav_sha256"]:
                        continue
                    voice = dict(entries[speaker], seed=str(seed))
                    submitted = words + mark
                    render_exact(engine, submitted, voice, wav)
                    done[clip_id] = {
                        "clip_id": clip_id, "line_id": line_id, "question_type": kind,
                        "speaker": speaker, "adapter_id": voice.get("adapter_id"),
                        "seed": seed, "arm": arm, "submitted_text": submitted,
                        "wav": os.path.abspath(wav), "wav_sha256": file_sha256(wav)}
                    atomic_json_write({"rows": list(done.values()),
                                       "provenance": provenance(__file__, args)}, rows_path)
                    print(f"[{len(done)}/{total}] {clip_id}: {submitted!r}", flush=True)

    with open(os.path.join(args.out_dir, "manifest.jsonl"), "w", encoding="utf-8") as handle:
        for row in done.values():
            handle.write(json.dumps({"id": row["clip_id"], "wav": row["wav"],
                                     "text": row["submitted_text"]}) + "\n")
    print(f"done: {len(done)}/{total} clips in {args.out_dir}")
    if len(done) != total:
        raise SystemExit(3)


if __name__ == "__main__":
    main()

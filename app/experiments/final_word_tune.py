"""Does a generated line END rising or falling? (#1519)

WHY. Vigneaux & Cole (arXiv:2610.27403) found that in staged TTS generators -
the family Qwen3-TTS belongs to - the final punctuation mark is the only
prompt-side lever that reliably moves the pitch at the end of a sentence. #1516
found speech preparation submitting authored questions as `?.`. Whether that
changes how the line sounds has never been measured; this is the instrument.

WHAT IT READS, following the paper's section 3, over the FINAL WORD only
(the paper shows the two punctuation conditions differ there and not before):

    excursion       mean ERB of the last fifth of voiced points minus the mean
                    of the first fifth. Positive = the word ends higher.
    offset          mean ERB of the last fifth, and the same relative to the
                    whole line's median, so voices at different pitches compare.
    voiced_fraction share of frames in the word with a pitch value.
    rising          excursion above RISE_BOUNDARY_ERB.

ERB, NOT HERTZ OR SEMITONES, because the paper reports in ERB and its +0.38
boundary is only comparable in the same unit. The conversion is Praat's
hertzToErb, since the paper tracked pitch with Praat. The +0.38 boundary was
fitted to THEIR models' assertions and questions; it is a starting point to be
re-checked on ours, not a constant. The continuous excursion is always recorded
beside the boolean.

PITCH TRACKER: PRAAT, NOT PYIN. The first pilot (2026-10-22, 40 clips, two
"husky" library LoRA voices) scored with `voice_compare_view.f0_contour`
(librosa pyin) left 27 of 40 final words unmeasured. pyin's voicing probability
sat near 0.01 on these voices even where Praat's autocorrelation tracker found
steady voicing at a plausible pitch ("boat": Praat 22 voiced 5-ms frames at
146 Hz, pyin 0 of 10). The paper also used Praat. A 5 ms step gives about four
times pyin's points over a 0.15-0.3 s final word.

PITCH CEILING. A ceiling that suits a voice's median cuts off the top of a
question rise in a higher voice, and losing exactly the top of a rise biases
the read-out toward "falling" (one pilot rise reached ~445 Hz). PITCH_CEILING_HZ
is 600; a test pins a 250->450 Hz rise that a 350 Hz ceiling loses.

PITCH RANGE: TWO PASSES (Hirst 2011; Hirst & De Looze 2020, ch. 13). A blind
listening check of 12 pilot clips matched the single-pass Praat read-out on
only 5 of the 10 clips the listener could call. The three large misses were
tracking errors, not intonation: a 3-frame 518-568 Hz burst after a 98->63 Hz
fall, a word whose first half was tracked an octave high, and a climb onto a
harmonic. The published fix tracks once at 60-700 Hz, then again between
0.75 x q1 and 1.5 x q3 of that first track. Hirst offers 2.5 x q3 for
expanded (expressive) ranges; the artifact records the read-out under both,
with 1.5 x q3 fixed as the primary before rescoring.

WORD END = END OF SPEECH. CTC marks a short spike, not where a word ends: in
the pilot the aligned end of the final word came 0.02-0.12 s before speech
stopped, cutting off the edge tone being measured. Since the final word is the
last thing said, its end is taken as the end of audible speech (LoCA's
activity rule, arXiv:2610.28035 Appendix D) whenever that is later.

UNMEASURED IS NOT FLAT. A word with too few voiced frames returns
`measured: False` with the reason, never an excursion of 0 (Rule 21: a fallback
that returns a plausible value is the dangerous kind).

Usage:
    python app/experiments/final_word_tune.py --manifest clips.jsonl --out tune.json
where each manifest line is {"id": ..., "wav": ..., "text": ...}.
"""
import argparse
import json
import math
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import atomic_json_write

RISE_BOUNDARY_ERB = 0.38
PITCH_FLOOR_HZ = 60
PITCH_CEILING_HZ = 700
FLOOR_Q1_FACTOR = 0.75
CEILING_Q3_FACTOR = 1.5
EXPANDED_CEILING_Q3_FACTOR = 2.5
PITCH_STEP_SECONDS = 0.005
MIN_VOICED_SECONDS = 0.06
MIN_VOICED_FRACTION = 0.25
ALIGN_MODEL = "facebook/wav2vec2-large-960h"


def hz_to_erb(hz):
    """Praat's hertzToErb: ERB-rate of a frequency in Hz."""
    return 11.17 * math.log((hz + 312.0) / (hz + 14680.0)) + 43.0


def get_words(text):
    """Alignment tokens for an English line: letters and apostrophes, upper case."""
    words = []
    for raw in text.split():
        word = re.sub(r"[^A-Za-z']", "", raw).upper().strip("'")
        if word:
            words.append(word)
    return words


def get_tune_readout(times, f0_hz, start, end, line_median_hz=None):
    """Read the final-word contour between start and end (seconds)."""
    inside = [(t, f) for t, f in zip(times, f0_hz) if start <= t <= end]
    voiced = [f for _t, f in inside if f is not None and not math.isnan(f)]
    fraction = len(voiced) / len(inside) if inside else 0.0
    base = {"start": round(start, 3), "end": round(end, 3),
            "frames": len(inside), "voiced_points": len(voiced),
            "voiced_fraction": round(fraction, 3)}
    if len(voiced) * PITCH_STEP_SECONDS < MIN_VOICED_SECONDS:
        return {**base, "measured": False, "reason": "too few voiced points"}
    if fraction < MIN_VOICED_FRACTION:
        return {**base, "measured": False, "reason": "voiced fraction too low"}
    erb = [hz_to_erb(f) for f in voiced]
    fifth = max(1, len(erb) // 5)
    first = sum(erb[:fifth]) / fifth
    last = sum(erb[-fifth:]) / fifth
    excursion = last - first
    result = {**base, "measured": True,
              "excursion_erb": round(excursion, 4),
              "offset_erb": round(last, 4),
              "rising": excursion > RISE_BOUNDARY_ERB}
    if line_median_hz:
        result["offset_vs_line_erb"] = round(last - hz_to_erb(line_median_hz), 4)
    return result


def get_pitch_contour(samples, rate, ceiling=PITCH_CEILING_HZ, floor=PITCH_FLOOR_HZ):
    """(times, f0 in Hz with NaN where unvoiced) from Praat's ac tracker."""
    import numpy as np
    import parselmouth

    sound = parselmouth.Sound(np.asarray(samples, dtype="float64"), sampling_frequency=rate)
    pitch = sound.to_pitch_ac(time_step=PITCH_STEP_SECONDS,
                              pitch_floor=floor, pitch_ceiling=ceiling)
    f0 = pitch.selected_array["frequency"].astype("float64")
    f0[f0 <= 0] = np.nan
    return list(pitch.xs()), f0.tolist()


def get_two_pass_contour(samples, rate, ceiling_q3_factor=CEILING_Q3_FACTOR):
    """Hirst's two-pass track: the second pass's range comes from the first's."""
    import numpy as np

    times, f0 = get_pitch_contour(samples, rate)
    voiced = [f for f in f0 if not np.isnan(f)]
    if len(voiced) < 4:
        return times, f0, None
    q1, q3 = np.percentile(voiced, [25, 75])
    floor, ceiling = FLOOR_Q1_FACTOR * q1, ceiling_q3_factor * q3
    times, f0 = get_pitch_contour(samples, rate, ceiling=ceiling, floor=floor)
    return times, f0, {"floor_hz": round(float(floor), 1), "ceiling_hz": round(float(ceiling), 1)}


def get_speech_end(samples, rate):
    """Seconds at which audible speech stops (LoCA's 50 ms RMS activity rule)."""
    import librosa
    import numpy as np

    rms = librosa.feature.rms(y=np.asarray(samples, dtype="float32"),
                              frame_length=int(0.05 * rate), hop_length=int(0.02 * rate))[0]
    threshold = float(np.clip(0.15 * np.percentile(rms, 95), 0.0003, 0.003))
    active = np.where(rms > threshold)[0]
    if not active.size:
        return None
    return float(librosa.frames_to_time(active[-1], sr=rate, hop_length=int(0.02 * rate)))


def get_final_word_span(wav, text, device="cpu", model_name=ALIGN_MODEL):
    """(start, end, score) of the line's last word, by known-text CTC alignment."""
    from ctc_text_boundary import align_lines

    words = get_words(text)
    if not words:
        raise ValueError(f"no alignable words in {text!r}")
    start, end, word = align_lines(wav, words, model_name, device)[-1]
    return start, end, word


def measure_clip(wav, text, device="cpu"):
    import numpy as np
    import soundfile

    samples, rate = soundfile.read(wav, dtype="float64", always_2d=True)
    samples = samples.mean(axis=1)
    start, ctc_end, word = get_final_word_span(wav, text, device)
    speech_end = get_speech_end(samples, rate)
    end = max(ctc_end, speech_end) if speech_end is not None else ctc_end
    readouts = {}
    for name, factor in (("primary", CEILING_Q3_FACTOR), ("expanded", EXPANDED_CEILING_Q3_FACTOR)):
        times, f0, pitch_range = get_two_pass_contour(samples, rate, factor)
        line_voiced = [f for f in f0 if not np.isnan(f)]
        median = float(np.median(line_voiced)) if line_voiced else None
        readouts[name] = {"pitch_range": pitch_range,
                          **get_tune_readout(times, f0, start, end, median)}
    return {"final_word": word, "ctc_end": round(ctc_end, 3),
            "speech_end": None if speech_end is None else round(speech_end, 3),
            **readouts["primary"], "expanded": readouts["expanded"]}


def main():
    from experiments.provenance import provenance

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    with open(args.manifest, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    results = []
    for row in rows:
        try:
            readout = measure_clip(row["wav"], row["text"], args.device)
        except Exception as error:  # recorded into the artifact, never a value
            readout = {"measured": False, "reason": f"{type(error).__name__}: {error}"}
        results.append({**row, **readout})
        print(json.dumps(results[-1]), flush=True)
    measured = [r for r in results if r.get("measured")]
    document = {"rise_boundary_erb": RISE_BOUNDARY_ERB, "tracker": "praat to_pitch_ac",
                "first_pass_hz": [PITCH_FLOOR_HZ, PITCH_CEILING_HZ],
                "second_pass": f"{FLOOR_Q1_FACTOR} x q1 to {CEILING_Q3_FACTOR} x q3 "
                               f"(expanded: {EXPANDED_CEILING_Q3_FACTOR} x q3)",
                "pitch_step_seconds": PITCH_STEP_SECONDS,
                "min_voiced_seconds": MIN_VOICED_SECONDS,
                "align_model": ALIGN_MODEL,
                "summary": {"clips": len(results), "measured": len(measured),
                            "rising": sum(1 for r in measured if r["rising"])},
                "rows": results, "provenance": provenance(__file__, args)}
    atomic_json_write(document, args.out)


if __name__ == "__main__":
    main()

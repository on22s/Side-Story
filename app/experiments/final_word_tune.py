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

PITCH CEILING. `f0_contour` defaults to 350 Hz, which is enough for a voice's
median but not for the top of a question rise in a higher voice: frames above
the ceiling come back unvoiced, and losing exactly the top of a rise biases the
read-out toward "falling". This uses FMAX_HZ instead; a test pins a 250->450 Hz
rise that the 350 Hz ceiling cannot measure.

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
FMAX_HZ = 600
MIN_VOICED_POINTS = 10
MIN_VOICED_FRACTION = 0.25
SAMPLE_RATE = 22050
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
    if len(voiced) < MIN_VOICED_POINTS:
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


def get_final_word_span(wav, text, device="cpu", model_name=ALIGN_MODEL):
    """(start, end, score) of the line's last word, by known-text CTC alignment."""
    from ctc_text_boundary import align_lines

    words = get_words(text)
    if not words:
        raise ValueError(f"no alignable words in {text!r}")
    start, end, word = align_lines(wav, words, model_name, device)[-1]
    return start, end, word


def measure_clip(wav, text, device="cpu"):
    import librosa
    import numpy as np
    from voice_compare_view import f0_contour

    y, sr = librosa.load(wav, sr=SAMPLE_RATE)
    times, f0 = f0_contour(y, sr, fmax=FMAX_HZ)
    if times is None:
        return {"measured": False, "reason": "no pitch track"}
    start, end, word = get_final_word_span(wav, text, device)
    line_voiced = f0[~np.isnan(f0)]
    median = float(np.median(line_voiced)) if line_voiced.size else None
    return {"final_word": word,
            **get_tune_readout(times.tolist(), f0.tolist(), start, end, median)}


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
    document = {"rise_boundary_erb": RISE_BOUNDARY_ERB, "fmax_hz": FMAX_HZ,
                "align_model": ALIGN_MODEL,
                "summary": {"clips": len(results), "measured": len(measured),
                            "rising": sum(1 for r in measured if r["rising"])},
                "rows": results, "provenance": provenance(__file__, args)}
    atomic_json_write(document, args.out)


if __name__ == "__main__":
    main()

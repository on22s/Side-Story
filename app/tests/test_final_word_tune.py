"""The final-word tune read-out behind #1519, checked where the answer is known.

Every pitch fixture is a synthetic harmonic tone whose F0 is set exactly, so the
true excursion is computed, not judged. The cases include ones the read-out must
REJECT: a flat tone and a rise too small to count are not rising, noise is
unmeasured rather than flat, and the old 350 Hz ceiling is shown to lose a high
rise, so the fixture keeps discriminating if PITCH_CEILING_HZ is ever lowered.
The end-of-speech rule is checked on a tone followed by silence.
"""
import math
import unittest

import numpy as np

from experiments import final_word_tune as tune

RATE = 22050
SECONDS = 0.5


def get_glide(start_hz, end_hz):
    """A harmonic tone whose F0 moves linearly from start_hz to end_hz."""
    t = np.arange(int(RATE * SECONDS)) / RATE
    f0 = start_hz + (end_hz - start_hz) * t / SECONDS
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    wave = sum(np.sin(k * phase) / k for k in range(1, 9))
    return (0.3 * wave / np.max(np.abs(wave))).astype("float32")


def get_true_excursion(start_hz, end_hz, times=None):
    """Excursion of the exact contour by the same last-fifth/first-fifth rule.

    With `times`, the true F0 is taken at those instants only: the frames the
    tracker reported as voiced. Praat's 50 ms window cannot centre a voiced
    frame in the first and last ~25 ms of a sound, so on a steep glide its
    first and last fifths sit slightly inside the true ones. Comparing at the
    tracker's own frames tests whether the pitch it reports is right;
    test_edge_frames_are_lost states the edge loss separately.
    """
    if times is None:
        times = np.linspace(0, SECONDS, 1000)
    f0 = start_hz + (end_hz - start_hz) * np.asarray(times) / SECONDS
    erb = [tune.hz_to_erb(f) for f in f0]
    fifth = max(1, len(erb) // 5)
    return float(np.mean(erb[-fifth:]) - np.mean(erb[:fifth]))


def get_voiced_times(y, ceiling=tune.PITCH_CEILING_HZ):
    times, f0 = tune.get_pitch_contour(y, RATE, ceiling=ceiling)
    return [t for t, f in zip(times, f0) if not np.isnan(f)]


def read(y, ceiling=tune.PITCH_CEILING_HZ):
    times, f0 = tune.get_pitch_contour(y, RATE, ceiling=ceiling)
    return tune.get_tune_readout(times, f0, 0.0, SECONDS)


class HzToErbTest(unittest.TestCase):
    def test_matches_paper_equation_6_reference_values(self):
        # Eq. 6 / author f0.py, independently evaluated numerical controls.
        for hz, erb in ((100, 3.36998188), (150, 4.68561453),
                        (450, 10.10691641), (1000, 15.62253891)):
            self.assertAlmostEqual(tune.hz_to_erb(hz), erb, places=5)

    def test_is_increasing(self):
        self.assertLess(tune.hz_to_erb(150), tune.hz_to_erb(151))


class TuneReadoutTest(unittest.TestCase):
    def test_borrowed_boundary_uses_the_paper_scale(self):
        # Praat hertzToErb gives 0.3682 and flips this same contour below 0.38.
        readout = tune.get_tune_readout(np.arange(30) * 0.005, [150.] * 24 + [166.] * 6, 0, 0.15)
        self.assertAlmostEqual(readout['excursion_erb'], 0.3845, places=4)
        self.assertTrue(readout['rising'])

    def assert_excursion(self, start_hz, end_hz, readout):
        self.assertTrue(readout["measured"], readout)
        times = get_voiced_times(get_glide(start_hz, end_hz))
        self.assertAlmostEqual(readout["excursion_erb"],
                               get_true_excursion(start_hz, end_hz, times), delta=0.15)

    def test_edge_frames_are_lost(self):
        # The tracker's voiced frames start and end inside the sound, which is
        # why a steep glide reads somewhat short of its whole-contour excursion.
        times = get_voiced_times(get_glide(250, 450))
        self.assertGreater(times[0], 0.0)
        self.assertLess(times[-1], SECONDS)
        self.assertLess(times[-1] - times[0], SECONDS - 0.03)

    def test_rise_reads_as_rising(self):
        readout = read(get_glide(150, 220))
        self.assert_excursion(150, 220, readout)
        self.assertTrue(readout["rising"])

    def test_fall_reads_as_falling(self):
        readout = read(get_glide(220, 150))
        self.assert_excursion(220, 150, readout)
        self.assertFalse(readout["rising"])

    def test_flat_tone_is_not_rising(self):
        readout = read(get_glide(180, 180))
        self.assertTrue(readout["measured"], readout)
        self.assertLess(abs(readout["excursion_erb"]), 0.1)
        self.assertFalse(readout["rising"])

    def test_rise_below_the_boundary_is_not_rising(self):
        # 180 -> 190 Hz is a true excursion of about 0.21 ERB, under +0.38.
        self.assertLess(get_true_excursion(180, 190), tune.RISE_BOUNDARY_ERB)
        readout = read(get_glide(180, 190))
        self.assert_excursion(180, 190, readout)
        self.assertFalse(readout["rising"])

    def test_high_rise_is_measured_above_the_old_ceiling(self):
        readout = read(get_glide(250, 450))
        self.assert_excursion(250, 450, readout)
        self.assertTrue(readout["rising"])

    def test_old_350_hz_ceiling_loses_the_high_rise(self):
        truth = get_true_excursion(250, 450)
        readout = read(get_glide(250, 450), ceiling=350)
        lost = (not readout["measured"]) or readout["excursion_erb"] < truth / 2
        self.assertTrue(lost, readout)

    def test_noise_is_unmeasured_not_flat(self):
        rng = np.random.default_rng(0)
        readout = read((0.1 * rng.standard_normal(int(RATE * SECONDS))).astype("float32"))
        self.assertFalse(readout["measured"], readout)
        self.assertNotIn("excursion_erb", readout)
        self.assertNotIn("rising", readout)

    def test_window_outside_the_contour_is_unmeasured(self):
        times, f0 = tune.get_pitch_contour(get_glide(150, 220), RATE)
        readout = tune.get_tune_readout(times, f0, 5.0, 6.0)
        self.assertFalse(readout["measured"])
        self.assertEqual(readout["frames"], 0)

    def test_offset_is_reported_against_the_line_median(self):
        times, f0 = tune.get_pitch_contour(get_glide(150, 220), RATE)
        readout = tune.get_tune_readout(times, f0, 0.0, SECONDS, 150.0)
        self.assertAlmostEqual(readout["offset_vs_line_erb"],
                               readout["offset_erb"] - tune.hz_to_erb(150.0), places=3)
        self.assertGreater(readout["offset_vs_line_erb"], 0)


class TwoPassTest(unittest.TestCase):
    def test_range_comes_from_the_first_pass_quartiles(self):
        times, f0, pitch_range = tune.get_two_pass_contour(get_glide(150, 220), RATE)
        self.assertIsNotNone(pitch_range)
        self.assertLess(pitch_range["floor_hz"], 150)
        self.assertGreater(pitch_range["ceiling_hz"], 220)

    def test_a_rise_survives_the_second_pass(self):
        times, f0, _ = tune.get_two_pass_contour(get_glide(250, 450), RATE)
        readout = tune.get_tune_readout(times, f0, 0.0, SECONDS)
        self.assertTrue(readout["measured"], readout)
        self.assertTrue(readout["rising"])

    def test_noise_has_no_range_and_stays_unmeasured(self):
        rng = np.random.default_rng(0)
        noise = (0.1 * rng.standard_normal(int(RATE * SECONDS))).astype("float32")
        times, f0, pitch_range = tune.get_two_pass_contour(noise, RATE)
        self.assertFalse(tune.get_tune_readout(times, f0, 0.0, SECONDS)["measured"])


class SpeechEndTest(unittest.TestCase):
    def test_end_is_where_the_tone_stops_not_the_file(self):
        samples = np.concatenate([get_glide(150, 220), np.zeros(int(RATE * 0.4), "float32")])
        self.assertAlmostEqual(tune.get_speech_end(samples, RATE), SECONDS, delta=0.05)

    def test_silence_has_no_speech_end(self):
        self.assertIsNone(tune.get_speech_end(np.zeros(RATE, "float32"), RATE))


class WordsTest(unittest.TestCase):
    def test_terminal_punctuation_never_becomes_a_word(self):
        self.assertEqual(tune.get_words("Will you wait by the gate?."),
                         ["WILL", "YOU", "WAIT", "BY", "THE", "GATE"])
        self.assertEqual(tune.get_words("Wait!."), ["WAIT"])

    def test_quotes_and_apostrophes(self):
        self.assertEqual(tune.get_words("“Isn't it?”"), ["ISN'T", "IT"])
        self.assertEqual(tune.get_words("'Really?'"), ["REALLY"])

    def test_text_without_words_is_empty(self):
        self.assertEqual(tune.get_words("?! ..."), [])


if __name__ == "__main__":
    unittest.main()

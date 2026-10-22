"""The final-word tune read-out behind #1519, checked where the answer is known.

Every pitch fixture is a synthetic harmonic tone whose F0 is set exactly, so the
true excursion is computed, not judged. The cases include ones the read-out must
REJECT: a flat tone and a rise too small to count are not rising, noise is
unmeasured rather than flat, and the old 350 Hz ceiling is shown to lose a high
rise, so the fixture keeps discriminating if FMAX_HZ is ever lowered.
"""
import math
import unittest

import numpy as np

from experiments import final_word_tune as tune
from experiments.voice_compare_view import f0_contour

RATE = tune.SAMPLE_RATE
SECONDS = 0.5


def get_glide(start_hz, end_hz):
    """A harmonic tone whose F0 moves linearly from start_hz to end_hz."""
    t = np.arange(int(RATE * SECONDS)) / RATE
    f0 = start_hz + (end_hz - start_hz) * t / SECONDS
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    wave = sum(np.sin(k * phase) / k for k in range(1, 9))
    return (0.3 * wave / np.max(np.abs(wave))).astype("float32")


def get_true_excursion(start_hz, end_hz):
    """Excursion of the exact contour, by the same last-fifth/first-fifth rule."""
    f0 = np.linspace(start_hz, end_hz, 1000)
    erb = [tune.hz_to_erb(f) for f in f0]
    return float(np.mean(erb[-200:]) - np.mean(erb[:200]))


def read(y, fmax=tune.FMAX_HZ):
    times, f0 = f0_contour(y, RATE, fmax=fmax)
    return tune.get_tune_readout(times.tolist(), f0.tolist(), 0.0, SECONDS)


class HzToErbTest(unittest.TestCase):
    def test_matches_praat_reference_values(self):
        # Printed by Praat itself (parselmouth, `hertzToErb`), not recalled.
        for hz, erb in ((100, 3.011324), (150, 4.253029),
                        (450, 9.618586), (1000, 15.289092)):
            self.assertAlmostEqual(tune.hz_to_erb(hz), erb, places=5)

    def test_is_increasing(self):
        self.assertLess(tune.hz_to_erb(150), tune.hz_to_erb(151))


class TuneReadoutTest(unittest.TestCase):
    def assert_excursion(self, start_hz, end_hz, readout):
        self.assertTrue(readout["measured"], readout)
        self.assertAlmostEqual(readout["excursion_erb"],
                               get_true_excursion(start_hz, end_hz), delta=0.15)

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
        readout = read(get_glide(250, 450), fmax=350)
        lost = (not readout["measured"]) or readout["excursion_erb"] < truth / 2
        self.assertTrue(lost, readout)

    def test_noise_is_unmeasured_not_flat(self):
        rng = np.random.default_rng(0)
        readout = read((0.1 * rng.standard_normal(int(RATE * SECONDS))).astype("float32"))
        self.assertFalse(readout["measured"], readout)
        self.assertNotIn("excursion_erb", readout)
        self.assertNotIn("rising", readout)

    def test_window_outside_the_contour_is_unmeasured(self):
        times, f0 = f0_contour(get_glide(150, 220), RATE, fmax=tune.FMAX_HZ)
        readout = tune.get_tune_readout(times.tolist(), f0.tolist(), 5.0, 6.0)
        self.assertFalse(readout["measured"])
        self.assertEqual(readout["frames"], 0)

    def test_offset_is_reported_against_the_line_median(self):
        times, f0 = f0_contour(get_glide(150, 220), RATE, fmax=tune.FMAX_HZ)
        readout = tune.get_tune_readout(times.tolist(), f0.tolist(), 0.0, SECONDS, 150.0)
        self.assertAlmostEqual(readout["offset_vs_line_erb"],
                               readout["offset_erb"] - tune.hz_to_erb(150.0), places=3)
        self.assertGreater(readout["offset_vs_line_erb"], 0)


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

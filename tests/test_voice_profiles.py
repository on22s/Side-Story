import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from voice_profiles import (  # noqa: E402
    bind_character_profile,
    inspect_reference,
    profile_import_url,
    validate_reference,
    write_manifest,
)


class VoiceProfileTests(unittest.TestCase):
    def test_inspect_accepts_canonical_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice.wav"
            sample_rate = 24000
            timeline = np.arange(sample_rate * 4, dtype=np.float32) / sample_rate
            audio = 0.2 * np.sin(2 * np.pi * 220 * timeline)
            sf.write(path, audio, sample_rate, subtype="PCM_16")
            metrics = inspect_reference(path)
            self.assertEqual(metrics.sample_rate, 24000)
            self.assertEqual(metrics.channels, 1)
            self.assertEqual(validate_reference(metrics), [])

    def test_profile_import_url_normalises_tts_endpoints(self):
        self.assertEqual(
            profile_import_url("http://127.0.0.1:18000/tts"),
            "http://127.0.0.1:18000/voice_profiles/import",
        )
        self.assertEqual(
            profile_import_url("https://tts.example/voice_profiles/design"),
            "https://tts.example/voice_profiles/import",
        )

    def test_bind_preserves_previous_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "books" / "fanren"
            state = book / "state"
            refs = root / "references"
            state.mkdir(parents=True)
            refs.mkdir()
            audio_path = refs / "ziling.wav"
            samples = 0.2 * np.sin(2 * np.pi * 220 * np.arange(24000 * 4) / 24000)
            sf.write(audio_path, samples, 24000, subtype="PCM_16")
            (state / "characters.json").write_text(json.dumps({
                "char_1": {"name": "紫灵", "voice_id": "voice_1"}
            }, ensure_ascii=False), encoding="utf-8")
            (state / "aliases.json").write_text(json.dumps({"紫灵": "char_1"}, ensure_ascii=False), encoding="utf-8")
            (state / "voices.json").write_text(json.dumps({
                "voice_1": {"type": "profile", "voice_profile_id": "vp_old"}
            }), encoding="utf-8")
            metrics = inspect_reference(audio_path)
            manifest_path = refs / "ziling.profile.json"
            manifest = write_manifest(
                manifest_path,
                audio_path=audio_path,
                metrics=metrics,
                speaker="紫灵",
                transcript="韩兄，再见面时，是不是该叫你一声韩老祖了？",
                description="清雅、从容、带笑",
                language="Chinese",
                source_url="https://example.test/source",
                source_title="authorised test source",
                rights_basis="unit test fixture",
                rights_confirmed=True,
            )
            result = bind_character_profile(book, "紫灵", "vp_ziling_v1", manifest)
            voices = json.loads((state / "voices.json").read_text(encoding="utf-8"))
            self.assertEqual(result["character_id"], "char_1")
            self.assertEqual(voices["voice_1"]["voice_profile_id"], "vp_ziling_v1")
            self.assertEqual(voices["voice_1"]["previous_voice_profile_id"], "vp_old")
            self.assertEqual(voices["voice_1"]["ref_text"], manifest["voice"]["transcript"])
            self.assertEqual(voices["voice_1"]["reference_audio"], "references/ziling.wav")


if __name__ == "__main__":
    unittest.main()

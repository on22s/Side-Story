import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_serial.py"
SPEC = importlib.util.spec_from_file_location("update_serial", SCRIPT)
assert SPEC and SPEC.loader
update_serial = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = update_serial
SPEC.loader.exec_module(update_serial)


class UpdateSerialProbeTests(unittest.TestCase):
    def test_parse_probe_data_builds_audiobookshelf_chapters(self):
        result = update_serial.parse_probe_data(
            {
                "chapters": [
                    {"id": 0, "start_time": "0", "end_time": "12.5", "tags": {"title": "第一章"}},
                    {"id": 1, "start_time": "12.5", "end_time": "25", "tags": {"title": "第二章"}},
                ],
                "format": {"duration": "25.0"},
            }
        )
        self.assertEqual(result.duration, 25.0)
        self.assertEqual(
            result.chapters[-1],
            {"start": 12.5, "end": 25.0, "title": "第二章", "id": 1},
        )

    def test_parse_probe_data_rejects_invalid_range(self):
        with self.assertRaises(update_serial.SerialUpdateError):
            update_serial.parse_probe_data(
                {
                    "chapters": [{"start_time": "5", "end_time": "5", "tags": {"title": "坏章节"}}],
                    "format": {"duration": "5"},
                }
            )

    def test_chapters_match_checks_count_and_last_title(self):
        expected = [{"title": "第一章"}, {"title": "第二章"}]
        self.assertTrue(update_serial.chapters_match(expected, expected))
        self.assertFalse(update_serial.chapters_match(expected[:1], expected))
        self.assertFalse(
            update_serial.chapters_match(
                [{"title": "第一章"}, {"title": "另一章"}], expected
            )
        )


if __name__ == "__main__":
    unittest.main()

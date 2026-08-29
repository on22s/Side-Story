from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cli


class BookConfigTests(unittest.TestCase):
    def test_book_override_deep_merges_global_tts_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            book_dir = Path(directory) / "english-book"
            book_dir.mkdir()
            cli.atomic_write_json(book_dir / "config.json", {
                "language": {"source": "en", "tts": "English", "prompt": "en"},
                "tts": {"voice_preset": "english_narrator"},
                "sfx": {"enabled": False},
            })
            global_config = {
                "tts": {
                    "mode": "external",
                    "url": "http://127.0.0.1:18000/tts",
                    "urls": [
                        "http://127.0.0.1:18000/tts",
                        "http://127.0.0.1:18001/tts",
                    ],
                    "voice_profile_urls": ["http://127.0.0.1:18000/voice_profiles/design"],
                    "parallel_workers": 2,
                },
                "sfx": {
                    "enabled": True,
                    "manifest": "assets/sfx/manifest.json",
                    "max_effects_per_chapter": 80,
                },
            }

            effective = cli.resolve_book_config(book_dir, global_config)

            self.assertEqual(effective["tts"]["urls"], global_config["tts"]["urls"])
            self.assertEqual(effective["tts"]["voice_profile_urls"], global_config["tts"]["voice_profile_urls"])
            self.assertEqual(effective["tts"]["language"], "English")
            self.assertEqual(effective["tts"]["voice_preset"], "english_narrator")
            self.assertFalse(effective["sfx"]["enabled"])
            self.assertEqual(effective["sfx"]["max_effects_per_chapter"], 80)

    def test_english_language_selects_prompt_and_voice_preset(self) -> None:
        config = {
            "language": {"source": "en", "tts": "English", "prompt": "en"},
            "tts": {"voice_preset": "english_narrator"},
        }

        self.assertEqual(cli.book_language_settings(config), {
            "source": "en",
            "tts": "English",
            "prompt": "en",
        })
        self.assertEqual(cli.book_voice_preset(config), "english_narrator")
        self.assertIn("English audiobook", cli.default_voices("english_narrator")["voice_narrator"]["style"])

    def test_config_change_invalidates_analysis_and_render_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            book_dir = Path(directory) / "book"
            chapter_dir = cli.chapter_root(book_dir, 1)
            chapter_dir.mkdir(parents=True)
            source_path = chapter_dir / "source.txt"
            source_path.write_text("The door opened.\n", encoding="utf-8")
            old_config = {
                "language": {"source": "zh", "tts": "Chinese", "prompt": "zh"},
                "tts": {"urls": ["http://127.0.0.1:18000/tts"]},
            }
            new_config = {
                "language": {"source": "en", "tts": "English", "prompt": "en"},
                "tts": {"urls": ["http://127.0.0.1:18000/tts"]},
            }
            status = cli.default_chapter_status(1, cli.sha256_file(source_path), old_config)
            status.update({
                "analysis": True,
                "summary": True,
                "voices": True,
                "tts": True,
                "done": True,
                "tts_lines_done": 3,
            })
            cli.atomic_write_json(chapter_dir / "status.json", status)

            current = cli.load_chapter_status(book_dir, 1, new_config)

            self.assertFalse(current["analysis"])
            self.assertFalse(current["summary"])
            self.assertFalse(current["voices"])
            self.assertFalse(current["tts"])
            self.assertFalse(current["done"])
            self.assertEqual(current["tts_lines_done"], 0)
            self.assertNotEqual(current["analysis_config_hash"], cli.analysis_config_fingerprint(new_config))
            self.assertNotEqual(current["render_config_hash"], cli.render_config_fingerprint(new_config))

    def test_init_writes_only_requested_book_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "novel.txt"
            input_path.write_text("The door opened.\n", encoding="utf-8")
            target = cli.init_project(
                root / "books", "english", input_path, language="English",
                voice_preset="english_narrator",
            )
            config = cli.read_json(target / "config.json", {})
            self.assertEqual(config["language"]["prompt"], "en")
            self.assertEqual(config["language"]["tts"], "English")
            self.assertEqual(config["tts"]["voice_preset"], "english_narrator")
            status = cli.read_json(cli.chapter_root(target, 1) / "status.json", {})
            effective = cli.resolve_book_config(target)
            self.assertEqual(status["analysis_config_hash"], cli.analysis_config_fingerprint(effective))

    def test_english_prompts_are_localized(self) -> None:
        pipeline = object.__new__(cli.BookPipeline)
        pipeline.prompt_locale = "en"
        pipeline.sfx_manifest = {}
        pipeline.chapter_label = lambda chapter: f"Chapter {chapter}"
        pipeline.related_context = lambda chapter, source: {"characters": [], "aliases": {}}
        pipeline._previous_context = lambda chapter: {"summary": "", "tail": []}

        script_prompt = pipeline._script_prompt(1, 1, 1, "The door opened.", [])
        summary_prompt = pipeline._summary_prompt(1, [{"speaker": "NARRATOR", "text": "The door opened."}])

        self.assertIn("English-language long-form audiobook", script_prompt)
        self.assertIn("The door opened.", script_prompt)
        self.assertIn("chapter summarizer for a long-form English audiobook", summary_prompt)
        self.assertNotIn("你是中文", script_prompt)
        self.assertNotIn("你是中文", summary_prompt)


if __name__ == "__main__":
    unittest.main()

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

    def test_audio_policy_uses_mobile_mono_m4b_defaults(self) -> None:
        settings = cli.audio_settings({})
        self.assertEqual(settings["mix_sample_rate"], 48000)
        self.assertEqual(settings["mix_channels"], 1)
        self.assertEqual(settings["mix_sample_format"], "pcm_s16le")
        self.assertEqual(settings["publish_sample_rate"], 44100)
        self.assertEqual(settings["publish_channels"], 1)
        self.assertEqual(settings["publish_bitrate"], "96k")
        self.assertEqual(
            cli.m4b_encode_args({})[-2:], ["-movflags", "+faststart"]
        )

    def test_no_generic_book_policy_creates_dedicated_profile_for_unnamed_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            book_dir = Path(directory) / "book"
            book_dir.mkdir()
            config = {
                "language": {"source": "en", "tts": "English", "prompt": "en"},
                "tts": {"voice_preset": "english_narrator"},
                "voices": {"no_generic": True},
            }
            cli.atomic_write_json(book_dir / "config.json", config)
            cli.atomic_write_json(book_dir / "book.json", {"book_id": "book", "chapters": []})
            cli.ensure_project_state(book_dir, config)

            pipeline = object.__new__(cli.BookPipeline)
            pipeline.book_dir = book_dir
            pipeline.book = {"book_id": "book"}
            pipeline.config = config
            pipeline.characters = {}
            pipeline.aliases = {}
            pipeline.voices = {}

            character_id, voice_id = pipeline._ensure_character(
                "Passenger", {"named": False}, 1
            )

            self.assertTrue(character_id)
            self.assertTrue(voice_id)
            self.assertNotIn("generic", voice_id)
            self.assertEqual(pipeline.voices[voice_id]["voice_type"], "persistent")
            self.assertNotIn(
                "voice_generic_male_middle",
                cli.read_json(book_dir / "state" / "voices.json", {}),
            )

    def test_book_role_assignment_reuses_fixed_character_voice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            book_dir = Path(directory) / "book"
            book_dir.mkdir()
            config = {
                "language": {"source": "en", "tts": "English", "prompt": "en"},
                "tts": {"voice_preset": "english_narrator"},
                "voices": {
                    "no_generic": True,
                    "role_aliases": {"Passenger": "Pencroft"},
                },
            }
            cli.atomic_write_json(book_dir / "config.json", config)
            cli.atomic_write_json(book_dir / "book.json", {"book_id": "book", "chapters": []})
            cli.ensure_project_state(book_dir, config)

            pipeline = object.__new__(cli.BookPipeline)
            pipeline.book_dir = book_dir
            pipeline.book = {"book_id": "book"}
            pipeline.config = config
            pipeline.characters = {
                "char_000001": {
                    "name": "Pencroft",
                    "aliases": ["Pencroft"],
                    "voice_id": None,
                    "first_seen": 1,
                    "last_seen": 1,
                },
            }
            pipeline.aliases = {"Pencroft": "char_000001"}
            pipeline.voices = {}

            character_id, voice_id = pipeline._ensure_character(
                "Passenger", {"named": False}, 1
            )

            self.assertEqual(character_id, "char_000001")
            self.assertEqual(pipeline.characters[character_id]["voice_id"], voice_id)
            self.assertNotIn("Passenger", pipeline.characters[character_id]["aliases"])

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

    def test_ordered_parts_map_rebuilds_global_chapter_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            book_dir = Path(directory) / "book"
            chapters = []
            internal = 0
            for part_length in (22, 20, 20):
                for part_chapter in range(1, part_length + 1):
                    internal += 1
                    chapter_dir = cli.chapter_root(book_dir, internal)
                    chapter_dir.mkdir(parents=True, exist_ok=True)
                    source = (
                        f"Chapter {part_chapter}\n"
                        "This is sufficiently long narrative text for testing the ordered "
                        "chapter map and its punctuation handling.\n"
                    )
                    source_path = chapter_dir / "source.txt"
                    source_path.write_text(source, encoding="utf-8")
                    chapters.append({
                        "number": internal,
                        "title": f"Chapter {part_chapter}",
                        "source_chars": len(source),
                    })

            maps = cli.novel_chapter_maps(book_dir, {
                "source_sha256": "source",
                "chaptering": {"mode": "ordered_parts"},
                "chapters": chapters,
            })

            self.assertEqual(len(maps["main"]), 62)
            self.assertEqual(maps["main"][1], 1)
            self.assertEqual(maps["main"][22], 22)
            self.assertEqual(maps["main"][23], 23)
            self.assertEqual(maps["main"][43], 43)
            self.assertEqual(maps["main"][62], 62)

    def test_split_chapters_can_drop_front_matter(self) -> None:
        text = "Cover\nProject Gutenberg license\n\nChapter 1\nThe storm began.\n\nChapter 2\nThe island appeared."

        chapters = cli.split_chapters(text, drop_front_matter=True)

        self.assertEqual([title for title, _ in chapters], ["Chapter 1", "Chapter 2"])

    def test_audiobook_source_skips_embedded_table_of_contents(self) -> None:
        text = (
            "The Mysterious Island\nCONTENTS\nPART 1. DROPPED FROM THE CLOUDS\n"
            "Chapter 1\nChapter 2\nPART 1—DROPPED FROM THE CLOUDS\n"
            "Chapter 1\n"
            "This is the actual first chapter with enough narrative text to distinguish it "
            "from the short table-of-contents entries.\n"
            "Chapter 2\n"
            "This is the actual second chapter with enough narrative text for the same check."
        )

        cleaned = cli._clean_audiobook_source(
            text, drop_front_matter=True, strip_part_headings=True
        )
        chapters = cli.split_chapters(cleaned)

        self.assertEqual([title for title, _ in chapters], ["Chapter 1", "Chapter 2"])
        self.assertIn("actual first chapter", chapters[0][1])
        self.assertNotIn("CONTENTS", cleaned)

    def test_audiobook_source_removes_gutenberg_running_headers_and_trailer(self) -> None:
        text = (
            "Chapter 1\n"
            "A sufficiently long opening paragraph is present here so that this is "
            "treated as a real chapter by the source cleaner.\n"
            "The Project Gutenberg eBook of The Mysterious Island, by Jules Verne\n"
            "*** END OF THE PROJECT GUTENBERG EBOOK 1268 ***\n"
            "Project Gutenberg license text"
        )

        cleaned = cli._clean_audiobook_source(text, drop_front_matter=True)

        self.assertNotIn("Project Gutenberg", cleaned)
        self.assertIn("opening paragraph", cleaned)

    def test_english_sentence_split_handles_periods_and_abbreviations(self) -> None:
        self.assertEqual(
            cli._split_sentences("Dr. Smith spoke. Then he left."),
            ["Dr. Smith spoke.", "Then he left."],
        )

    def test_english_long_text_does_not_cut_known_word(self) -> None:
        text = "This is a sentence with ordinary English punctuation. " * 30

        chunks = cli.split_natural(text, max_chars=100)

        self.assertGreater(len(chunks), 1)
        self.assertFalse(any(chunk.endswith("punct") for chunk in chunks))
        self.assertFalse(any(chunk.startswith("uation") for chunk in chunks))


if __name__ == "__main__":
    unittest.main()

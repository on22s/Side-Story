from __future__ import annotations

import os
import socket
import unittest
from unittest import mock

import cli


class AnalysisPromptTests(unittest.TestCase):
    def make_pipeline(self) -> cli.BookPipeline:
        pipeline = object.__new__(cli.BookPipeline)
        pipeline.sfx_manifest = {
            "sword_clash": {
                "category": "combat",
                "description": "兵器碰撞",
                "loop": False,
            },
            "mountain_wind": {
                "category": "ambience",
                "description": "山间风声",
                "loop": True,
            },
        }
        pipeline.chapter_label = lambda chapter: f"第{chapter}章"
        pipeline.related_context = lambda chapter, source: {
            "characters": [{
                "character_id": "char_1",
                "name": "韩立",
                "aliases": ["韩道友"],
                "gender": "male",
                "age": "young_adult",
                "description": "沉稳",
                "voice_id": "must_not_be_sent",
            }],
            "aliases": {"韩道友": "char_1"},
        }
        pipeline._previous_context = lambda chapter: {
            "summary": "上一章摘要",
            "tail": [{
                "speaker": "韩立",
                "character_id": "char_1",
                "voice_id": "must_not_be_sent",
                "voice_profile_id": "also_must_not_be_sent",
                "text": "上一章末句。",
                "effects": [],
            }],
        }
        return pipeline

    def test_first_chunk_prompt_has_grounded_contract_and_trimmed_context(self) -> None:
        pipeline = self.make_pipeline()
        source = "韩立说道：\n“走吧。”"
        prompt = pipeline._script_prompt(7, 1, 3, source, [])

        self.assertIn("逐字一致，包括引号和标点", prompt)
        self.assertIn("任何真实对白都不得归 NARRATOR", prompt)
        self.assertIn("代词、临时外貌描述和不确定猜测不要报告", prompt)
        self.assertIn('"previous_chapter_summary":"上一章摘要"', prompt)
        self.assertIn(source, prompt)
        self.assertNotIn("voice_id", prompt)
        self.assertNotIn("voice_profile_id", prompt)

    def test_later_chunk_uses_current_tail_instead_of_previous_chapter(self) -> None:
        pipeline = self.make_pipeline()
        previous_entries = [{
            "speaker": "韩立",
            "character_id": "char_1",
            "voice_id": "voice_1",
            "text": "本章前文。",
            "effects": [],
        }]
        prompt = pipeline._script_prompt(7, 2, 3, "他转过身。", previous_entries)

        self.assertIn('"current_chapter_tail"', prompt)
        self.assertIn("本章前文。", prompt)
        self.assertNotIn("上一章摘要", prompt)
        self.assertNotIn("voice_1", prompt)

    def test_coverage_accepts_whitespace_only_segmentation_changes(self) -> None:
        pipeline = self.make_pipeline()
        pipeline._validate_script_coverage(7, "他说：\n“走吧。”", {
            "script": [
                {"text": "他说："},
                {"text": "“走吧。”"},
            ],
        })

    def test_coverage_rejects_missing_or_rewritten_characters(self) -> None:
        pipeline = self.make_pipeline()
        with mock.patch.dict(os.environ, {"ALEXANDRIA_COVERAGE_MODE": "strict"}):
            with self.assertRaisesRegex(cli.PipelineError, "未逐字覆盖原文"):
                pipeline._validate_script_coverage(7, "他说：“走吧。”", {
                    "script": [
                        {"text": "他说："},
                        {"text": "走。"},
                    ],
                })

    def test_coverage_repairs_a_tiny_same_length_substitution(self) -> None:
        pipeline = self.make_pipeline()
        result = {
            "script": [
                {"speaker": "NARRATOR", "text": "他推诿道："},
                {"speaker": "韩立", "text": "“走吧。”"},
            ],
        }

        with mock.patch.dict(os.environ, {"ALEXANDRIA_COVERAGE_MODE": "strict"}):
            pipeline._validate_script_coverage(7, "他推辞道：“走吧。”", result)

        self.assertEqual(result["script"][0]["text"], "他推辞道：")
        self.assertEqual(result["script"][1]["text"], "“走吧。”")

    def test_coverage_rejects_many_same_length_substitutions(self) -> None:
        pipeline = self.make_pipeline()
        with mock.patch.dict(os.environ, {"ALEXANDRIA_COVERAGE_MODE": "strict"}):
            with self.assertRaisesRegex(cli.PipelineError, "未逐字覆盖原文"):
                pipeline._validate_script_coverage(7, "甲" * 2000, {
                    "script": [{"text": "乙" * 2000}],
                })

    def test_coverage_is_disabled_by_default(self) -> None:
        pipeline = self.make_pipeline()
        result = {"script": [{"text": "少量改写也继续。"}]}

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALEXANDRIA_COVERAGE_MODE", None)
            pipeline._validate_script_coverage(7, "原文不同。", result)

        self.assertEqual(result["script"][0]["text"], "少量改写也继续。")

    def test_coverage_warn_mode_allows_missing_text(self) -> None:
        pipeline = self.make_pipeline()
        result = {"script": [{"text": "他说：走。"}]}

        with mock.patch.dict(os.environ, {"ALEXANDRIA_COVERAGE_MODE": "warn"}):
            pipeline._validate_script_coverage(7, "他说：“走吧。”", result)

        self.assertEqual(result["script"][0]["text"], "他说：走。")

    def test_codex_proxy_preflight_rejects_dead_loopback_proxy(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            unused_port = probe.getsockname()[1]
        with mock.patch.dict(
            os.environ,
            {"HTTPS_PROXY": f"http://127.0.0.1:{unused_port}"},
            clear=True,
        ):
            with self.assertRaisesRegex(cli.PipelineError, "Codex 代理不可用"):
                cli.CodexRunner._validate_local_proxy()


if __name__ == "__main__":
    unittest.main()

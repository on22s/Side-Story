from __future__ import annotations

import unittest

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
        with self.assertRaisesRegex(cli.PipelineError, "未逐字覆盖原文"):
            pipeline._validate_script_coverage(7, "他说：“走吧。”", {
                "script": [
                    {"text": "他说："},
                    {"text": "走。"},
                ],
            })


if __name__ == "__main__":
    unittest.main()

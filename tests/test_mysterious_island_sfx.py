from __future__ import annotations

import unittest
from pathlib import Path

import cli


class MysteriousIslandSoundEffectTests(unittest.TestCase):
    def test_book_catalog_is_complete_and_all_assets_are_local(self) -> None:
        book_dir = cli.ROOT_DIR / "books" / "mysterious_island"
        config = cli.resolve_book_config(book_dir)
        manifest_path, manifest = cli.load_sfx_manifest(config)

        self.assertEqual(
            manifest_path,
            (book_dir / "sfx_manifest.json").resolve(),
        )
        self.assertEqual(len(manifest), 55)
        self.assertEqual(
            sum(bool(record.get("loop")) for record in manifest.values()),
            19,
        )
        self.assertEqual(
            sum(not bool(record.get("loop")) for record in manifest.values()),
            36,
        )
        self.assertTrue(config["sfx"]["enabled"])
        for record in manifest.values():
            self.assertTrue(Path(record["path"]).is_file())


if __name__ == "__main__":
    unittest.main()

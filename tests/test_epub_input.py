from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import cli


class EpubInputTests(unittest.TestCase):
    def test_navigation_and_cover_spine_entries_are_not_narrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            files = {
                "META-INF/container.xml": (
                    '<?xml version="1.0"?>'
                    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                    'media-type="application/oebps-package+xml"/></rootfiles></container>'
                ),
                "OEBPS/content.opf": (
                    '<?xml version="1.0"?>'
                    '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
                    '<manifest>'
                    '<item id="cover" href="titlepage.xhtml" media-type="application/xhtml+xml"/>'
                    '<item id="toc" href="toc.xhtml" media-type="application/xhtml+xml"/>'
                    '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
                    '</manifest><spine>'
                    '<itemref idref="cover"/><itemref idref="toc"/><itemref idref="chapter"/>'
                    '</spine></package>'
                ),
                "OEBPS/titlepage.xhtml": "<html><body><h1>Cover Title</h1></body></html>",
                "OEBPS/toc.xhtml": "<html><body><h1>Navigation Only</h1><p>Chapter 1</p></body></html>",
                "OEBPS/chapter.xhtml": "<html><body><h1>Chapter 1</h1><p>Actual prose.</p></body></html>",
            }
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("mimetype", "application/epub+zip")
                for name, content in files.items():
                    archive.writestr(name, content)

            text = cli.read_book_input(path)

            self.assertIn("Actual prose.", text)
            self.assertNotIn("Navigation Only", text)
            self.assertNotIn("Cover Title", text)


if __name__ == "__main__":
    unittest.main()

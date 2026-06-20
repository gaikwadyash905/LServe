import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lserve


class SearchFilterTests(unittest.TestCase):
    def test_search_filters_journal_year_and_open_access(self):
        payload = {
            "results": [
                {
                    "id": "1",
                    "display_name": "Paper A",
                    "publication_year": 2022,
                    "doi": "https://doi.org/10.1/a",
                    "primary_location": {
                        "landing_page_url": "https://example.com/a",
                        "pdf_url": "https://example.com/a.pdf",
                        "source": {"display_name": "Nature"},
                    },
                    "open_access": {"is_oa": True, "oa_url": "https://example.com/a.pdf"},
                    "authorships": [],
                },
                {
                    "id": "2",
                    "display_name": "Paper B",
                    "publication_year": 2018,
                    "primary_location": {
                        "landing_page_url": "https://example.com/b",
                        "source": {"display_name": "Random Journal"},
                    },
                    "open_access": {"is_oa": False},
                    "authorships": [],
                },
            ]
        }

        with patch("lserve._fetch_json", return_value=payload):
            results = lserve.search_papers(
                keywords="deep learning",
                journals=["nature"],
                year_from=2020,
                open_access_only=True,
                limit=10,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Paper A")


class ShortlistTests(unittest.TestCase):
    def test_add_is_deduplicated_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            shortlist_path = Path(tmp) / "shortlist.json"
            shortlist = lserve.Shortlist(shortlist_path)
            paper = lserve.Paper(
                id="x",
                title="Example",
                journal="Nature",
                year=2024,
                doi=None,
                landing_page_url="https://example.com",
                pdf_url="https://example.com/file.pdf",
                is_open_access=True,
                citation="citation",
            )

            self.assertTrue(shortlist.add(paper))
            self.assertFalse(shortlist.add(paper))

            reloaded = lserve.Shortlist(shortlist_path)
            self.assertEqual(len(reloaded.items), 1)
            self.assertEqual(reloaded.items[0].id, "x")

    def test_download_all_uses_pdf_or_landing_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            shortlist_path = Path(tmp) / "shortlist.json"
            out_dir = Path(tmp) / "out"
            shortlist = lserve.Shortlist(shortlist_path)
            shortlist.items = [
                lserve.Paper(
                    id="1",
                    title="With PDF",
                    journal="J1",
                    year=2024,
                    doi=None,
                    landing_page_url="https://example.com/1",
                    pdf_url="https://example.com/1.pdf",
                    is_open_access=True,
                    citation="c1",
                ),
                lserve.Paper(
                    id="2",
                    title="Without PDF",
                    journal="J2",
                    year=2024,
                    doi=None,
                    landing_page_url="https://example.com/2",
                    pdf_url=None,
                    is_open_access=False,
                    citation="c2",
                ),
            ]

            calls = []

            def fake_retrieve(url, path):
                calls.append((url, Path(path)))
                Path(path).write_text("x", encoding="utf-8")

            with patch("urllib.request.urlretrieve", side_effect=fake_retrieve):
                files = shortlist.download_all(out_dir)

            self.assertEqual(len(files), 2)
            self.assertEqual(calls[0][0], "https://example.com/1.pdf")
            self.assertEqual(calls[1][0], "https://example.com/2")


class CitationExportTests(unittest.TestCase):
    def test_export_citations_creates_plain_text_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            shortlist_path = Path(tmp) / "shortlist.json"
            citations_path = Path(tmp) / "citations.txt"
            shortlist = lserve.Shortlist(shortlist_path)
            shortlist.items = [
                lserve.Paper(
                    id="1",
                    title="Paper",
                    journal="J",
                    year=2023,
                    doi=None,
                    landing_page_url=None,
                    pdf_url=None,
                    is_open_access=True,
                    citation="Doe, \"Paper\", J, 2023",
                )
            ]

            shortlist.export_citations(citations_path)
            self.assertEqual(citations_path.read_text(encoding="utf-8"), "Doe, \"Paper\", J, 2023\n")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""LServe: Literature survey assistant CLI."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from urllib.error import URLError
from json import JSONDecodeError
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_SHORTLIST_PATH = Path(".lserve_shortlist.json")
DEFAULT_LAST_SEARCH_PATH = Path(".lserve_last_search.json")
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
REQUEST_TIMEOUT_SECONDS = 20
OVERFETCH_FACTOR = 3
MIN_FETCH_SIZE = 25
MAX_FETCH_SIZE = 200
MAX_AUTHORS_SHOWN = 4
MAX_FILENAME_STEM_LENGTH = 80
MAX_FILENAME_ATTEMPTS = 1000


@dataclass
class Paper:
    id: str
    title: str
    journal: str
    year: int | None
    doi: str | None
    landing_page_url: str | None
    pdf_url: str | None
    is_open_access: bool
    citation: str


def _fetch_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Failed to fetch OpenAlex data: {url}") from exc
    except JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from OpenAlex API: {url}") from exc


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_")
    return cleaned or "paper"


def _next_unique_path(target_dir: Path, base_name: str, extension: str) -> Path:
    candidate = target_dir / f"{base_name}{extension}"
    if not candidate.exists():
        return candidate
    counter = 2
    while counter <= MAX_FILENAME_ATTEMPTS:
        candidate = target_dir / f"{base_name}_{counter}{extension}"
        if not candidate.exists():
            return candidate
        counter += 1
    raise RuntimeError(f"Could not create unique filename for '{base_name}' after {MAX_FILENAME_ATTEMPTS} tries")


def _download_file(source_url: str, destination_path: Path) -> None:
    try:
        with urllib.request.urlopen(source_url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            destination_path.write_bytes(response.read())
    except (URLError, OSError) as exc:
        raise RuntimeError(f"Failed downloading {source_url}") from exc


def _calculate_fetch_size(limit: int) -> int:
    return min(max(limit * OVERFETCH_FACTOR, MIN_FETCH_SIZE), MAX_FETCH_SIZE)


def _to_citation(raw: dict[str, Any]) -> str:
    authors = raw.get("authorships", [])
    names = [a.get("author", {}).get("display_name") for a in authors]
    names = [n for n in names if n]
    author_text = ", ".join(names[:MAX_AUTHORS_SHOWN]) if names else "Unknown"
    if len(names) > MAX_AUTHORS_SHOWN:
        author_text += " et al."
    title = raw.get("display_name", "Untitled")
    year = raw.get("publication_year")
    journal = (
        raw.get("primary_location", {})
        .get("source", {})
        .get("display_name", "Unknown Journal")
    )
    doi = raw.get("doi")
    parts = [author_text, f'"{title}"', journal]
    if year:
        parts.append(str(year))
    if doi:
        parts.append(doi)
    return ", ".join(parts)


def _paper_from_openalex(raw: dict[str, Any]) -> Paper:
    location = raw.get("primary_location") or {}
    source = location.get("source") or {}
    open_access = raw.get("open_access") or {}
    best_oa = open_access.get("oa_url")
    pdf_url = location.get("pdf_url") or best_oa

    return Paper(
        id=raw.get("id", ""),
        title=raw.get("display_name", "Untitled"),
        journal=source.get("display_name", "Unknown Journal"),
        year=raw.get("publication_year"),
        doi=raw.get("doi"),
        landing_page_url=location.get("landing_page_url"),
        pdf_url=pdf_url,
        is_open_access=bool(open_access.get("is_oa")),
        citation=_to_citation(raw),
    )


def search_papers(
    keywords: str,
    journals: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    open_access_only: bool = False,
    limit: int = 20,
) -> list[Paper]:
    # Overfetch because we apply journal/year/open-access filtering after retrieval.
    query: dict[str, str] = {
        "search": keywords,
        "per-page": str(_calculate_fetch_size(limit)),
    }
    url = f"{OPENALEX_WORKS_URL}?{urllib.parse.urlencode(query)}"
    payload = _fetch_json(url)
    papers = [_paper_from_openalex(item) for item in payload.get("results", [])]

    normalized_journals = [j.strip().lower() for j in journals or [] if j.strip()]

    filtered: list[Paper] = []
    for paper in papers:
        if normalized_journals and not any(j in paper.journal.lower() for j in normalized_journals):
            continue
        if year_from and (paper.year is None or paper.year < year_from):
            continue
        if year_to and (paper.year is None or paper.year > year_to):
            continue
        if open_access_only and not paper.is_open_access:
            continue
        filtered.append(paper)
        if len(filtered) >= limit:
            break
    return filtered


class Shortlist:
    def __init__(self, path: Path = DEFAULT_SHORTLIST_PATH):
        self.path = path
        self.items: list[Paper] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.items = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except JSONDecodeError as exc:
            raise RuntimeError(f"Invalid shortlist JSON: {self.path}") from exc
        self.items = [Paper(**item) for item in raw]

    def save(self) -> None:
        self.path.write_text(
            json.dumps([asdict(item) for item in self.items], indent=2),
            encoding="utf-8",
        )

    def add(self, paper: Paper) -> bool:
        if any(item.id == paper.id for item in self.items):
            return False
        self.items.append(paper)
        self.save()
        return True

    def export_citations(self, path: Path) -> None:
        lines = [item.citation for item in self.items]
        content = "\n".join(lines)
        if content:
            content += "\n"
        path.write_text(content, encoding="utf-8")

    def download_all(self, target_dir: Path) -> list[Path]:
        target_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []
        for item in self.items:
            source = item.pdf_url or item.landing_page_url
            if not source:
                continue
            extension = ".pdf" if item.pdf_url else ".html"
            output_path = _next_unique_path(
                target_dir, _safe_filename(item.title)[:MAX_FILENAME_STEM_LENGTH], extension
            )
            try:
                _download_file(source, output_path)
            except RuntimeError as exc:
                print(f"Failed to download '{item.title}' ({item.id}): {exc}")
                continue
            downloaded.append(output_path)
        return downloaded


class SearchCache:
    def __init__(self, path: Path = DEFAULT_LAST_SEARCH_PATH):
        self.path = path

    def save(self, papers: list[Paper]) -> None:
        self.path.write_text(
            json.dumps([asdict(item) for item in papers], indent=2),
            encoding="utf-8",
        )

    def load(self) -> list[Paper]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except JSONDecodeError as exc:
            raise RuntimeError(f"Invalid search cache JSON: {self.path}") from exc
        return [Paper(**item) for item in raw]


def _parse_journals(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _print_search_results(results: list[Paper]) -> None:
    if not results:
        print("No papers found.")
        return
    for idx, paper in enumerate(results, start=1):
        year_text = str(paper.year) if paper.year else "n/a"
        oa_text = "Open" if paper.is_open_access else "Closed"
        print(f"[{idx}] {paper.title}")
        print(f"    Journal: {paper.journal} | Year: {year_text} | Access: {oa_text}")
        if paper.doi:
            print(f"    DOI: {paper.doi}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Literature survey helper")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Search papers")
    search.add_argument("keywords", help="Search keywords")
    search.add_argument("--journals", help="Comma separated journal names")
    search.add_argument("--year-from", type=int)
    search.add_argument("--year-to", type=int)
    search.add_argument("--open-access", action="store_true")
    search.add_argument("--limit", type=int, default=20)

    add = sub.add_parser("add", help="Add paper by index from last search")
    add.add_argument("index", type=int)

    sub.add_parser("list", help="List shortlisted papers")

    download = sub.add_parser("download", help="Download all shortlisted papers")
    download.add_argument("--dir", default="downloads")

    citations = sub.add_parser("citations", help="Export shortlisted citations")
    citations.add_argument("--out", default="citations.txt")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    shortlist = Shortlist()
    cache = SearchCache()

    if args.command == "search":
        results = search_papers(
            keywords=args.keywords,
            journals=_parse_journals(args.journals),
            year_from=args.year_from,
            year_to=args.year_to,
            open_access_only=args.open_access,
            limit=args.limit,
        )
        cache.save(results)
        _print_search_results(results)
        return 0

    if args.command == "add":
        cached = cache.load()
        if not cached:
            print("No cached search results. Run 'search' first.")
            return 1
        if args.index < 1 or args.index > len(cached):
            print(f"Index out of range. Choose 1..{len(cached)}")
            return 1
        added = shortlist.add(cached[args.index - 1])
        print("Added to shortlist." if added else "Paper already shortlisted.")
        return 0

    if args.command == "list":
        if not shortlist.items:
            print("Shortlist is empty.")
            return 0
        _print_search_results(shortlist.items)
        return 0

    if args.command == "download":
        files = shortlist.download_all(Path(args.dir))
        print(f"Downloaded {len(files)} files to {args.dir}")
        return 0

    if args.command == "citations":
        shortlist.export_citations(Path(args.out))
        print(f"Saved citations to {args.out}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

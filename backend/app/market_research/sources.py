from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class SourceItem:
    source: str
    source_id: str
    url: str
    title: str
    text: str
    author_hash: str | None = None
    published_at: dt.datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


HN_QUERIES = [
    '"stock research" OR "equity analysis" OR "earnings call"',
    '"SEC filings" OR "10-K" OR "10-Q" OR "investor research"',
    '"financial analysis tool" OR "investment research tool"',
    '"AI stock research" OR "ChatGPT investing" OR "investment chatbot"',
    '"finfluencer" OR "stock tips" OR "social media investing"',
    '"ETF research" OR "ETF screener" OR "thematic ETF"',
    '"investor relations" OR "retail investors" OR "shareholder Q&A"',
]


def _clean_text(value: str | None, *, max_chars: int = 4000) -> str:
    if not value:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _hash_author(source: str, author: str | None) -> str | None:
    if not author:
        return None
    return hashlib.sha256(f"{source}:{author}".encode("utf-8")).hexdigest()[:32]


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


async def fetch_hacker_news_items(
    *,
    client: httpx.AsyncClient,
    queries: list[str] | None = None,
    lookback_hours: int = 24,
    limit_per_query: int = 20,
) -> list[SourceItem]:
    cutoff_ts = int((dt.datetime.now(dt.UTC) - dt.timedelta(hours=lookback_hours)).timestamp())
    items: list[SourceItem] = []

    for query in queries or HN_QUERIES:
        resp = await client.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "query": query,
                "tags": "story,comment",
                "numericFilters": f"created_at_i>{cutoff_ts}",
                "hitsPerPage": limit_per_query,
            },
        )
        resp.raise_for_status()
        for hit in resp.json().get("hits", []):
            object_id = str(hit.get("objectID") or "")
            title = _clean_text(hit.get("title") or hit.get("story_title") or "HN discussion", max_chars=300)
            text = _clean_text(hit.get("comment_text") or hit.get("story_text") or title)
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
            if not object_id or not text:
                continue
            items.append(
                SourceItem(
                    source="hacker_news",
                    source_id=object_id,
                    url=url,
                    title=title,
                    text=text,
                    author_hash=_hash_author("hacker_news", hit.get("author")),
                    published_at=_parse_datetime(hit.get("created_at")),
                    metadata={
                        "query": query,
                        "points": hit.get("points"),
                        "num_comments": hit.get("num_comments"),
                        "story_id": hit.get("story_id"),
                    },
                )
            )
    return items


async def fetch_rss_items(
    *,
    client: httpx.AsyncClient,
    urls: list[str],
    lookback_hours: int = 24,
    limit_per_feed: int = 20,
) -> list[SourceItem]:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=lookback_hours)
    out: list[SourceItem] = []
    for feed_url in urls:
        if not feed_url:
            continue
        resp = await client.get(feed_url)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        entries = root.findall(".//item") or root.findall("{http://www.w3.org/2005/Atom}entry")
        for entry in entries[:limit_per_feed]:
            title = _clean_text(_first_text(entry, ["title", "{http://www.w3.org/2005/Atom}title"]), max_chars=300)
            link = _entry_link(entry) or feed_url
            published = _parse_datetime(
                _first_text(
                    entry,
                    [
                        "pubDate",
                        "published",
                        "updated",
                        "{http://www.w3.org/2005/Atom}published",
                        "{http://www.w3.org/2005/Atom}updated",
                    ],
                )
            )
            if published and published < cutoff:
                continue
            summary = _clean_text(
                _first_text(
                    entry,
                    [
                        "description",
                        "summary",
                        "content",
                        "{http://www.w3.org/2005/Atom}summary",
                        "{http://www.w3.org/2005/Atom}content",
                    ],
                )
            )
            source_id = _first_text(entry, ["guid", "id", "{http://www.w3.org/2005/Atom}id"]) or link
            text = summary or title
            if not text:
                continue
            out.append(
                SourceItem(
                    source="rss",
                    source_id=hashlib.sha256(f"{feed_url}:{source_id}".encode("utf-8")).hexdigest()[:40],
                    url=link,
                    title=title or "RSS item",
                    text=text,
                    published_at=published,
                    metadata={"feed_url": feed_url},
                )
            )
    return out


def _first_text(entry: ET.Element, names: list[str]) -> str | None:
    for name in names:
        child = entry.find(name)
        if child is not None and child.text:
            return child.text
    return None


def _entry_link(entry: ET.Element) -> str | None:
    link = _first_text(entry, ["link"])
    if link:
        return link
    atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is not None:
        return atom_link.attrib.get("href")
    return None

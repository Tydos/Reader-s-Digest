#!/usr/bin/env python3
"""Fetch interesting articles from the web (Refind-style digest)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
import yaml
from dateutil import parser as date_parser

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    from duckduckgo_search import DDGS

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "interests.yaml"
SOURCES_PATH = ROOT / "config" / "sources.txt"
ARTICLES_PATH = ROOT / "data" / "articles.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("fetch_articles")

TIMEMAP = {"day": "d", "week": "w", "month": "m", "d": "d", "w": "w", "m": "m"}
HN_API = "https://hn.algolia.com/api/v1/search"

# Skip list pages, social, and non-article URLs
_NOISE_PATH_RE = re.compile(
    r"/(login|signup|subscribe|pricing|about|contact|tag/|tags/|category/|"
    r"categories/|author/|authors/|search|feed|rss|newsletter|podcast|"
    r"collections/|page/\d+/?$|forms/)(/|$)",
    re.I,
)
_NOISE_HOST_RE = re.compile(
    r"(twitter\.com|x\.com|facebook\.com|instagram\.com|youtube\.com|"
    r"reddit\.com|linkedin\.com|tiktok\.com|pinterest\.com|bing\.com)$",
    re.I,
)
_NOISE_TITLE_RE = re.compile(
    r"\b(sign up|log in|subscribe now|cookie policy|privacy policy|"
    r"newsletter|category:|tag:|collection)\b",
    re.I,
)


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_sources() -> list[str]:
    sources: list[str] = []
    for line in SOURCES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            sources.append(line)
    return sources


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def article_id_for(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def domain_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def looks_like_article(url: str, title: str) -> bool:
    if not url or not title:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.netloc.lower()
    if _NOISE_HOST_RE.search(host):
        return False
    if _NOISE_PATH_RE.search(parsed.path or ""):
        return False
    if _NOISE_TITLE_RE.search(title):
        return False
    if "aclick" in (parsed.path or ""):
        return False
    parts = [p for p in (parsed.path or "").split("/") if p]
    # Require article-like depth; allow dated paths (/2026/07/...) or slugs
    if len(parts) < 2 and not parsed.path.endswith(".html"):
        if not re.search(r"/\d{4}/", parsed.path or ""):
            return False
    return True


def parse_date(raw: Any) -> str | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw, tz=timezone.utc).date().isoformat()
        dt = date_parser.parse(str(raw))
        return dt.date().isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def make_article(
    *,
    title: str,
    url: str,
    topic: str,
    summary: str,
    source: str | None,
    published_at: str | None,
    fetched_at: str,
    score: int | None = None,
) -> dict[str, Any]:
    return {
        "id": article_id_for(url),
        "title": title.strip(),
        "url": url.strip(),
        "topic": topic,
        "summary": summary.strip()[:500] if summary else "",
        "source": source or domain_from_url(url),
        "publishedAt": published_at,
        "fetchedAt": fetched_at,
        "score": score,
    }


def fetch_hackernews(
    interests: list[str],
    time_range: str,
    min_points: int,
    max_per_topic: int,
    fetched_at: str,
) -> list[dict[str, Any]]:
    days = {"day": 1, "week": 7, "month": 30, "d": 1, "w": 7, "m": 30}.get(
        time_range, 7
    )
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    articles: list[dict[str, Any]] = []

    for topic in interests:
        try:
            resp = requests.get(
                HN_API,
                params={
                    "query": topic,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{since},points>={min_points}",
                    "hitsPerPage": max_per_topic,
                },
                timeout=20,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits") or []
        except requests.RequestException as exc:
            log.warning("HN fetch failed for %r: %s", topic, exc)
            continue

        kept = 0
        for hit in hits:
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            title = hit.get("title") or ""
            if not looks_like_article(url, title):
                continue
            published = parse_date(hit.get("created_at_i"))
            summary = hit.get("story_text") or hit.get("comment_text") or ""
            if not summary and hit.get("points"):
                summary = f"{hit['points']} points on Hacker News"
            articles.append(
                make_article(
                    title=title,
                    url=url,
                    topic=topic,
                    summary=summary,
                    source="news.ycombinator.com",
                    published_at=published,
                    fetched_at=fetched_at,
                    score=hit.get("points"),
                )
            )
            kept += 1
        log.info("HN %r → %d articles", topic, kept)

    return articles


def search_topic_on_source(
    ddgs: DDGS,
    topic: str,
    source: str,
    time_range: str,
    max_results: int,
    fetched_at: str,
) -> list[dict[str, Any]]:
    query = f'"{topic}" site:{source}'
    timelimit = TIMEMAP.get(time_range, "w")
    try:
        results = list(ddgs.text(query, max_results=max_results, timelimit=timelimit))
    except Exception as exc:  # noqa: BLE001
        log.warning("Search failed %s on %s: %s", topic, source, exc)
        return []

    articles: list[dict[str, Any]] = []
    for result in results:
        url = result.get("href") or result.get("link") or ""
        title = (result.get("title") or "").strip()
        body = (result.get("body") or result.get("snippet") or "").strip()
        if not looks_like_article(url, title):
            continue
        published = parse_date(result.get("date"))
        articles.append(
            make_article(
                title=title,
                url=url,
                topic=topic,
                summary=body,
                source=source,
                published_at=published,
                fetched_at=fetched_at,
            )
        )
    return articles


def fetch_web_sources(
    interests: list[str],
    sources: list[str],
    time_range: str,
    max_per_source: int,
    max_sources_per_topic: int,
    delay: float,
    fetched_at: str,
) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    # Rotate sources so daily runs surface different publications over time
    day_offset = datetime.now(timezone.utc).toordinal() % max(len(sources), 1)
    rotated = sources[day_offset:] + sources[:day_offset]

    with DDGS() as ddgs:
        for topic in interests:
            topic_sources = rotated[:max_sources_per_topic]
            for i, source in enumerate(topic_sources):
                batch = search_topic_on_source(
                    ddgs, topic, source, time_range, max_per_source, fetched_at
                )
                articles.extend(batch)
                if batch:
                    log.info("Web %r @ %s → %d", topic, source, len(batch))
                if i < len(topic_sources) - 1:
                    time.sleep(delay)
    return articles


def load_existing() -> dict[str, Any]:
    if not ARTICLES_PATH.exists():
        return {"lastUpdated": None, "interests": [], "articles": []}
    with ARTICLES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def prune_articles(
    articles: list[dict[str, Any]], retention_days: int
) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    kept: list[dict[str, Any]] = []
    for article in articles:
        url = article.get("url") or ""
        title = article.get("title") or ""
        if url and not looks_like_article(url, title):
            continue
        if title and _NOISE_TITLE_RE.search(title):
            continue
        ts = article.get("publishedAt") or article.get("fetchedAt")
        if not ts:
            kept.append(article)
            continue
        try:
            dt = date_parser.parse(str(ts))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                kept.append(article)
        except (ValueError, TypeError, OverflowError):
            kept.append(article)
    return kept


def merge_articles(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    retention_days: int,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for article in existing:
        by_id[article["id"]] = article
    for article in incoming:
        prev = by_id.get(article["id"])
        if prev:
            article["publishedAt"] = article.get("publishedAt") or prev.get("publishedAt")
            article["score"] = article.get("score") or prev.get("score")
        by_id[article["id"]] = article

    merged = prune_articles(list(by_id.values()), retention_days)

    def sort_key(a: dict[str, Any]) -> tuple:
        score = a.get("score") or 0
        published = a.get("publishedAt") or ""
        fetched = a.get("fetchedAt") or ""
        return (score, published, fetched)

    merged.sort(key=sort_key, reverse=True)
    return merged


def fetch_all(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    interests = list(config.get("interests") or ["artificial intelligence"])
    time_range = config.get("timeRange") or "week"
    use_hn = bool(config.get("useHackerNews", True))
    hn_min = int(config.get("hnMinPoints") or 30)
    max_per_topic = int(config.get("maxPerTopic") or 12)
    max_per_source = int(config.get("maxPerSource") or 6)
    max_sources_per_topic = int(config.get("maxSourcesPerTopic") or 6)
    delay = float(config.get("delaySeconds") or 1.0)
    retention = int(config.get("retentionDays") or 14)

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    incoming: list[dict[str, Any]] = []

    if use_hn:
        incoming.extend(
            fetch_hackernews(interests, time_range, hn_min, max_per_topic, fetched_at)
        )

    sources = load_sources()
    if sources:
        incoming.extend(
            fetch_web_sources(
                interests,
                sources,
                time_range,
                max_per_source,
                max_sources_per_topic,
                delay,
                fetched_at,
            )
        )

    existing_data = load_existing()
    merged = merge_articles(
        existing_data.get("articles") or [], incoming, retention
    )

    payload = {
        "lastUpdated": fetched_at,
        "interests": interests,
        "articles": merged,
    }

    ARTICLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ARTICLES_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    log.info(
        "Wrote %d articles (%d new this run) to %s",
        len(merged),
        len(incoming),
        ARTICLES_PATH,
    )
    return payload


def main() -> None:
    fetch_all()


if __name__ == "__main__":
    main()

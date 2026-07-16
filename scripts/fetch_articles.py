#!/usr/bin/env python3
"""Fetch articles from Hacker News and configured web sources."""

from __future__ import annotations

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
    if len(parts) < 2 and not parsed.path.endswith(".html"):
        if not re.search(r"/\d{4}/", parsed.path or ""):
            return False
    return True


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def make_article(*, title: str, url: str, text: str) -> dict[str, str]:
    return {
        "title": title.strip(),
        "text": clean_text(text),
        "url": url.strip(),
    }


def fetch_hackernews(
    interests: list[str],
    time_range: str,
    min_points: int,
    max_per_topic: int,
) -> list[dict[str, str]]:
    days = {"day": 1, "week": 7, "month": 30, "d": 1, "w": 7, "m": 30}.get(
        time_range, 7
    )
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    articles: list[dict[str, str]] = []

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
            url = hit.get("url") or (
                f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            )
            title = hit.get("title") or ""
            if not looks_like_article(url, title):
                continue
            text = hit.get("story_text") or hit.get("comment_text") or ""
            if not text and hit.get("points"):
                text = f"{hit['points']} points on Hacker News"
            articles.append(make_article(title=title, url=url, text=text))
            kept += 1
        log.info("HN %r → %d articles", topic, kept)

    return articles


def search_topic_on_source(
    ddgs: DDGS,
    topic: str,
    source: str,
    time_range: str,
    max_results: int,
) -> list[dict[str, str]]:
    query = f'"{topic}" site:{source}'
    timelimit = TIMEMAP.get(time_range, "w")
    try:
        results = list(ddgs.text(query, max_results=max_results, timelimit=timelimit))
    except Exception as exc:  # noqa: BLE001
        log.warning("Search failed %s on %s: %s", topic, source, exc)
        return []

    articles: list[dict[str, str]] = []
    for result in results:
        url = result.get("href") or result.get("link") or ""
        title = (result.get("title") or "").strip()
        text = (result.get("body") or result.get("snippet") or "").strip()
        if not looks_like_article(url, title):
            continue
        articles.append(make_article(title=title, url=url, text=text))
    return articles


def fetch_web_sources(
    interests: list[str],
    sources: list[str],
    time_range: str,
    max_per_source: int,
    max_sources_per_topic: int,
    delay: float,
) -> list[dict[str, str]]:
    articles: list[dict[str, str]] = []
    topic_sources = sources[:max_sources_per_topic]

    with DDGS() as ddgs:
        for topic in interests:
            for i, source in enumerate(topic_sources):
                batch = search_topic_on_source(
                    ddgs, topic, source, time_range, max_per_source
                )
                articles.extend(batch)
                if batch:
                    log.info("Web %r @ %s → %d", topic, source, len(batch))
                if i < len(topic_sources) - 1:
                    time.sleep(delay)
    return articles


def dedupe(articles: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for article in articles:
        key = normalize_url(article["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(article)
    return unique


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

    incoming: list[dict[str, str]] = []

    if use_hn:
        incoming.extend(
            fetch_hackernews(interests, time_range, hn_min, max_per_topic)
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
            )
        )

    articles = dedupe(incoming)
    payload = {"articles": articles}

    ARTICLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ARTICLES_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    log.info("Wrote %d articles to %s", len(articles), ARTICLES_PATH)
    return payload


def main() -> None:
    fetch_all()


if __name__ == "__main__":
    main()

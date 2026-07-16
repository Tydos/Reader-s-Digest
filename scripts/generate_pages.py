#!/usr/bin/env python3
"""Generate a minimal static reading page from data/articles.json."""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_PATH = ROOT / "data" / "articles.json"
DOCS_DIR = ROOT / "docs"
DOCS_HTML_PATH = DOCS_DIR / "index.html"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("generate_pages")


def load_articles() -> dict[str, Any]:
    with ARTICLES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def card_html(article: dict[str, Any]) -> str:
    title = html.escape(article.get("title") or "Untitled")
    text = html.escape(article.get("text") or "")
    url = html.escape(article.get("url") or "#", quote=True)
    url_label = html.escape(article.get("url") or "")
    text_block = f'<p class="text">{text}</p>' if text else ""
    return f"""    <article class="card">
      <h2>{title}</h2>
      {text_block}
      <a href="{url}" target="_blank" rel="noopener noreferrer">{url_label}</a>
    </article>"""


def build_html(articles: list[dict[str, Any]]) -> str:
    if articles:
        cards = "\n".join(card_html(a) for a in articles)
    else:
        cards = '    <p class="empty">No articles yet. Run <code>python scripts/update.py</code>.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Reading Digest</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
      background: #fafafa;
      color: #111;
      line-height: 1.5;
      padding: 2rem 1rem 3rem;
    }}
    main {{
      max-width: 640px;
      margin: 0 auto;
    }}
    h1 {{
      margin: 0 0 0.25rem;
      font-size: 1.5rem;
      font-weight: 650;
    }}
    .meta {{
      color: #666;
      font-size: 0.9rem;
      margin: 0 0 1.5rem;
    }}
    .card {{
      background: #fff;
      border: 1px solid #e5e5e5;
      border-radius: 10px;
      padding: 1rem 1.1rem;
      margin-bottom: 0.75rem;
    }}
    .card h2 {{
      margin: 0 0 0.4rem;
      font-size: 1.05rem;
      font-weight: 600;
      line-height: 1.35;
    }}
    .card .text {{
      margin: 0 0 0.6rem;
      color: #444;
      font-size: 0.95rem;
    }}
    .card a {{
      color: #2563eb;
      font-size: 0.85rem;
      word-break: break-all;
      text-decoration: none;
    }}
    .card a:hover {{ text-decoration: underline; }}
    .empty {{ color: #666; }}
  </style>
</head>
<body>
  <main>
    <h1>Reading Digest</h1>
    <p class="meta">{len(articles)} articles</p>
{cards}
  </main>
</body>
</html>
"""


def generate(data: dict[str, Any] | None = None) -> None:
    data = data or load_articles()
    articles = data.get("articles") or []
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_HTML_PATH.write_text(build_html(articles), encoding="utf-8")
    log.info("Wrote %s (%d articles)", DOCS_HTML_PATH, len(articles))


def main() -> None:
    generate()


if __name__ == "__main__":
    main()

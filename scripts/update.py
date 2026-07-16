#!/usr/bin/env python3
"""Fetch articles and regenerate the reading page."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_pages import generate, load_articles  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("update")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch articles and regenerate the reading page."
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Only regenerate pages from existing data/articles.json",
    )
    args = parser.parse_args()

    if args.skip_fetch:
        log.info("Skipping fetch; regenerating from existing data")
        data = load_articles()
    else:
        from fetch_articles import fetch_all  # noqa: E402

        data = fetch_all()

    generate(data)
    log.info("Done.")


if __name__ == "__main__":
    main()

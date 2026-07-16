#!/usr/bin/env python3
"""Orchestrate article fetch + page generation."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_articles import (  # noqa: E402
    ARTICLES_PATH,
    fetch_all,
    load_config,
    load_existing,
    prune_articles,
)
from generate_pages import generate  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("update")


def prune_and_save() -> dict:
    config = load_config()
    retention = int(config.get("retentionDays") or 14)
    data = load_existing()
    before = len(data.get("articles") or [])
    data["articles"] = prune_articles(data.get("articles") or [], retention)
    after = len(data["articles"])
    with ARTICLES_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info("Pruned articles %d → %d", before, after)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch interesting articles and regenerate README + Pages."
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Only regenerate pages from existing data/articles.json",
    )
    args = parser.parse_args()

    if args.skip_fetch:
        log.info("Skipping fetch; pruning + regenerating from existing data")
        data = prune_and_save()
        generate(data)
    else:
        data = fetch_all()
        generate(data)

    log.info("Done.")


if __name__ == "__main__":
    main()

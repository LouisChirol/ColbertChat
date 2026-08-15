#!/usr/bin/env python3
"""Download BOFiP data and optionally ingest into Chroma."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

try:
    from database.sources.bofip.download import download_records
    from database.sources.bofip.ingest import BofipIngestor
except ImportError:
    from sources.bofip.download import download_records
    from sources.bofip.ingest import BofipIngestor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BOFiP download + ingest pipeline")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--probe-only", action="store_true", help="Download then exit")
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument(
        "--records-dir", type=Path, default=Path("data/bofip/records")
    )
    parser.add_argument("--max-documents", type=int, default=-1)
    parser.add_argument("--max-cost-usd", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.skip_download:
        logger.info("Step 1: Downloading BOFiP vigueur records…")
        manifest = download_records(args.records_dir)
        logger.info(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        logger.info("Skipping download")

    if args.probe_only:
        logger.info("Probe-only mode — run probe.py next")
        return 0

    ingestor = BofipIngestor(args.records_dir, max_documents=args.max_documents)
    files = ingestor._list_records()
    estimate = ingestor.estimate_embed_cost(files)
    logger.info(f"Embed estimate: {estimate}")

    if args.estimate_only:
        print(json.dumps(estimate, indent=2))
        return 0

    if args.skip_embed:
        logger.info("Skipping embed as requested")
        return 0

    if args.max_cost_usd is not None and estimate["estimated_cost_usd"] > args.max_cost_usd:
        logger.error(
            f"Estimated ${estimate['estimated_cost_usd']} > max ${args.max_cost_usd}"
        )
        return 1

    logger.info("Step 2: Ingesting into Chroma collection 'bofip'…")
    result = ingestor.run()
    logger.success(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

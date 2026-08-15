"""Download BOFiP publications en vigueur from data.economie.gouv.fr."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

import requests
from loguru import logger

API_BASE = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/bofip-vigueur/records"
)
PAGE_SIZE = 100
DEFAULT_OUTPUT_DIR = Path("data/bofip/records")
MANIFEST_PATH = Path("data/bofip/manifest.json")


def _safe_filename(identifiant: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", identifiant.strip())
    return cleaned or "unknown"


def _fetch_page(offset: int) -> Dict[str, Any]:
    response = requests.get(
        API_BASE,
        params={"limit": PAGE_SIZE, "offset": offset},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def download_records(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Dict[str, Any]:
    """Fetch all in-force BOFiP records and write one JSON file per document."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir.parent / "manifest.json"

    first = _fetch_page(0)
    total_count = int(first["total_count"])
    logger.info(f"BOFiP vigueur: {total_count} records to download")

    written = 0
    total_chars = 0
    series_counts: Dict[str, int] = {}

    offsets = list(range(0, total_count, PAGE_SIZE))
    for offset in offsets:
        payload = first if offset == 0 else _fetch_page(offset)
        for record in payload.get("results", []):
            ident = record.get("identifiant_juridique") or record.get("permalien", "")
            path = output_dir / f"{_safe_filename(ident)}.json"
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1
            content = record.get("contenu") or ""
            total_chars += len(content)
            serie = record.get("serie") or "unknown"
            series_counts[serie] = series_counts.get(serie, 0) + 1

        if offset + PAGE_SIZE < total_count:
            time.sleep(0.2)

    manifest = {
        "source": "bofip-vigueur",
        "api": API_BASE,
        "total_records": written,
        "total_content_chars": total_chars,
        "series_counts": dict(sorted(series_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "output_dir": str(output_dir),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.success(
        f"Downloaded {written} BOFiP records ({total_chars:,} chars) to {output_dir}"
    )
    return manifest


def main() -> None:
    manifest = download_records()
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

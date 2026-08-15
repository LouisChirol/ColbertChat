"""Validate BOFiP corpus relevance without embedding (keyword retrieval smoke test)."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from loguru import logger

DEFAULT_RECORDS_DIR = Path("data/bofip/records")

# Questions where BOFiP should add value beyond Service-Public procedural fiches.
SAMPLE_QUERIES = [
    "Quelles sont les règles de déduction de la TVA pour un auto-entrepreneur ?",
    "Comment contester un redressement fiscal devant le tribunal administratif ?",
    "Quelle est la doctrine sur la résidence fiscale en France ?",
    "Règles d'imposition des plus-values immobilières",
    "Cotisation foncière des entreprises exonération",
    "Déclaration d'impôt en ligne délai de prescription",
    "Micro-entreprise franchise en base de TVA",
    "Impôt sur le revenu abattement forfaitaire",
]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    return re.sub(r"[^a-z0-9\s]", " ", text)


def _tokenize(text: str) -> List[str]:
    return [t for t in _normalize(text).split() if len(t) > 2]


def load_records(records_dir: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted(records_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["_path"] = str(path)
        records.append(record)
    return records


def corpus_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    series = Counter(r.get("serie") or "unknown" for r in records)
    lengths = [len((r.get("contenu") or "")) for r in records]
    nonempty = [n for n in lengths if n > 0]
    return {
        "total_records": len(records),
        "nonempty_records": len(nonempty),
        "total_chars": sum(nonempty),
        "avg_chars": int(sum(nonempty) / max(len(nonempty), 1)),
        "top_series": series.most_common(15),
    }


def score_record(query_tokens: List[str], record: Dict[str, Any]) -> float:
    title = record.get("titre") or ""
    content = record.get("contenu") or ""
    serie = record.get("serie") or ""
    ident = record.get("identifiant_juridique") or ""
    haystack_tokens = _tokenize(f"{title} {serie} {ident} {content[:4000]}")
    if not haystack_tokens:
        return 0.0
    haystack = set(haystack_tokens)
    overlap = sum(1 for token in query_tokens if token in haystack)
    title_boost = sum(2 for token in query_tokens if token in _tokenize(title))
    ident_boost = sum(3 for token in query_tokens if token in _tokenize(ident))
    return overlap + title_boost + ident_boost


def search(
    records: List[Dict[str, Any]], query: str, top_k: int = 3
) -> List[Tuple[float, Dict[str, Any]]]:
    query_tokens = _tokenize(query)
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for record in records:
        score = score_record(query_tokens, record)
        if score > 0:
            scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:top_k]


def format_hit(score: float, record: Dict[str, Any]) -> str:
    content = (record.get("contenu") or "").strip()
    preview = content[:280].replace("\n", " ")
    return (
        f"score={score:.1f} | {record.get('identifiant_juridique')} | "
        f"{record.get('serie')} | {record.get('titre', '')[:90]}\n"
        f"  url: {record.get('permalien')}\n"
        f"  preview: {preview}..."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe BOFiP corpus relevance")
    parser.add_argument(
        "--records-dir", type=Path, default=DEFAULT_RECORDS_DIR
    )
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--top-k", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.records_dir.exists():
        logger.error(
            f"No records at {args.records_dir}. Run: "
            "python -m database.sources.bofip.download"
        )
        return 1

    records = load_records(args.records_dir)
    stats = corpus_stats(records)
    print("=== BOFiP corpus stats ===")
    print(json.dumps(stats, indent=2, ensure_ascii=False))

    queries = args.query or SAMPLE_QUERIES
    print("\n=== Relevance smoke test (keyword, no embeddings) ===")
    for query in queries:
        hits = search(records, query, top_k=args.top_k)
        print(f"\nQ: {query}")
        if not hits:
            print("  (no keyword hits)")
            continue
        for score, record in hits:
            print(f"  - {format_hit(score, record)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

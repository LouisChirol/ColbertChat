#!/usr/bin/env python3
"""
Retrieval evaluation utility.

Usage:
1) Bootstrap an eval set with expected doc IDs from current index state:
   python scripts/eval_retrieval.py --bootstrap
2) Run retrieval accuracy metrics after DB updates:
   python scripts/eval_retrieval.py
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Add backend root to import app package
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.retrieval import DocumentRetriever  # noqa: E402


DEFAULT_EVAL_SET_PATH = BACKEND_DIR / "evals" / "retrieval_eval_set.jsonl"

# 40 curated administrative questions (FR) to keep this evaluation cheap and practical.
DEFAULT_QUESTIONS = [
    "Comment renouveler mon passeport ?",
    "Quels documents fournir pour une première carte d'identité ?",
    "Comment déclarer un changement d'adresse après un déménagement ?",
    "Comment faire une pré-demande de carte d'identité en ligne ?",
    "Comment obtenir un extrait d'acte de naissance ?",
    "Comment demander un extrait de casier judiciaire bulletin n°3 ?",
    "Quelles démarches pour s'inscrire sur les listes électorales ?",
    "Comment obtenir une copie de mon livret de famille ?",
    "Comment signaler la perte de ma carte grise ?",
    "Comment immatriculer un véhicule d'occasion acheté en France ?",
    "Comment déclarer la vente de mon véhicule ?",
    "Comment demander un permis de conduire international ?",
    "Comment renouveler mon permis de conduire ?",
    "Comment contester une amende routière ?",
    "Comment demander la prime d'activité ?",
    "Comment faire une demande de RSA ?",
    "Comment demander les APL ?",
    "Comment déclarer mes ressources à la CAF ?",
    "Comment obtenir l'attestation de droits à l'assurance maladie ?",
    "Comment demander la Complémentaire santé solidaire ?",
    "Comment déclarer mes impôts en ligne ?",
    "Comment corriger une déclaration d'impôt déjà envoyée ?",
    "Comment demander un délai de paiement pour mes impôts ?",
    "Comment payer la taxe foncière ?",
    "Comment obtenir un avis de situation déclarative à l'impôt sur le revenu ?",
    "Comment créer mon espace Urssaf auto-entrepreneur ?",
    "Comment déclarer mon chiffre d'affaires en micro-entreprise ?",
    "Comment obtenir un extrait Kbis ?",
    "Comment modifier les statuts de ma société ?",
    "Comment fermer une micro-entreprise ?",
    "Comment demander un certificat de nationalité française ?",
    "Comment obtenir une attestation d'accueil pour un étranger ?",
    "Comment demander un titre de séjour ?",
    "Comment renouveler mon titre de séjour étudiant ?",
    "Comment demander l'aide juridictionnelle ?",
    "Comment saisir le Défenseur des droits ?",
    "Comment signaler une fraude à la carte bancaire ?",
    "Comment faire une procuration de vote ?",
    "Comment obtenir la médaille d'honneur du travail ?",
    "Comment consulter mes points de permis de conduire ?",
]


@dataclass
class EvalSample:
    id: str
    question: str
    expected_doc_ids: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retrieval-only evaluation.")
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=DEFAULT_EVAL_SET_PATH,
        help=f"Path to eval set JSON file (default: {DEFAULT_EVAL_SET_PATH})",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create/refresh eval set expected doc IDs from current retrieval results.",
    )
    parser.add_argument(
        "--expected-per-question",
        type=int,
        default=2,
        help="How many expected doc IDs to store during bootstrap.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Dense retrieval candidate count (before reranking).",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=8,
        help="Final docs kept after reranking.",
    )
    parser.add_argument(
        "--k-values",
        type=str,
        default="1,3,5,8",
        help="Comma-separated cutoffs for hit@k and recall@k.",
    )
    parser.add_argument(
        "--use-query-rewrite",
        action="store_true",
        help="Use generate_search_query() before retrieval (uses Mistral).",
    )
    parser.add_argument(
        "--show-failures",
        type=int,
        default=10,
        help="How many misses to print (0 to disable).",
    )
    return parser.parse_args()


def _retrieve_ids(
    retriever: DocumentRetriever,
    question: str,
    top_k: int,
    max_docs: int,
    use_query_rewrite: bool,
) -> list[str]:
    query = question
    if use_query_rewrite:
        query = retriever.generate_search_query(question, history=None)

    docs = retriever.retrieve_documents(query=query, top_k=top_k, max_docs=max_docs)
    ids: list[str] = []
    for doc in docs:
        if doc.id and doc.id not in ids:
            ids.append(doc.id)
    return ids


def bootstrap_eval_set(
    retriever: DocumentRetriever,
    eval_set_path: Path,
    expected_per_question: int,
    top_k: int,
    max_docs: int,
    use_query_rewrite: bool,
) -> None:
    eval_set_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for idx, question in enumerate(DEFAULT_QUESTIONS, start=1):
        predicted_ids = _retrieve_ids(
            retriever,
            question=question,
            top_k=top_k,
            max_docs=max(max_docs, expected_per_question),
            use_query_rewrite=use_query_rewrite,
        )
        rows.append(
            {
                "id": f"q{idx:03d}",
                "question": question,
                "expected_doc_ids": predicted_ids[:expected_per_question],
            }
        )

    serialized_rows = "\n".join(
        json.dumps(row, ensure_ascii=False) for row in rows
    )
    eval_set_path.write_text(serialized_rows + "\n", encoding="utf-8")
    print(f"Bootstrapped {len(rows)} eval samples to: {eval_set_path}")


def load_eval_samples(eval_set_path: Path) -> list[EvalSample]:
    if not eval_set_path.exists():
        raise FileNotFoundError(
            f"Eval set not found at {eval_set_path}. Run with --bootstrap first."
        )

    raw_lines = [
        line.strip()
        for line in eval_set_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    raw = [json.loads(line) for line in raw_lines]
    samples = [
        EvalSample(
            id=row["id"],
            question=row["question"],
            expected_doc_ids=row.get("expected_doc_ids", []),
        )
        for row in raw
    ]
    return samples


def evaluate(
    retriever: DocumentRetriever,
    samples: list[EvalSample],
    top_k: int,
    max_docs: int,
    k_values: list[int],
    use_query_rewrite: bool,
    show_failures: int,
) -> None:
    usable_samples = [s for s in samples if s.expected_doc_ids]
    skipped = len(samples) - len(usable_samples)

    if not usable_samples:
        raise ValueError("No samples with expected_doc_ids found in eval set.")

    hit_counts = {k: 0 for k in k_values}
    recall_sums = {k: 0.0 for k in k_values}
    reciprocal_rank_sum = 0.0
    failures: list[dict] = []

    for sample in usable_samples:
        predicted_ids = _retrieve_ids(
            retriever,
            question=sample.question,
            top_k=top_k,
            max_docs=max_docs,
            use_query_rewrite=use_query_rewrite,
        )
        expected = sample.expected_doc_ids

        first_relevant_rank = None
        for rank, doc_id in enumerate(predicted_ids, start=1):
            if doc_id in expected:
                first_relevant_rank = rank
                break

        if first_relevant_rank is not None:
            reciprocal_rank_sum += 1.0 / first_relevant_rank

        for k in k_values:
            top_ids = predicted_ids[:k]
            overlap = set(top_ids) & set(expected)
            if overlap:
                hit_counts[k] += 1
            recall_sums[k] += len(overlap) / len(expected)

        if not (set(predicted_ids) & set(expected)):
            failures.append(
                {
                    "id": sample.id,
                    "question": sample.question,
                    "expected": expected,
                    "predicted": predicted_ids,
                }
            )

    n = len(usable_samples)
    print(f"Evaluated {n} samples (skipped {skipped} without expectations)")
    print(f"Config: top_k={top_k}, max_docs={max_docs}, rewrite={use_query_rewrite}")
    print("")
    for k in k_values:
        hit_at_k = hit_counts[k] / n
        recall_at_k = recall_sums[k] / n
        print(f"hit@{k}: {hit_at_k:.3f} | recall@{k}: {recall_at_k:.3f}")
    print(f"mrr@{max_docs}: {reciprocal_rank_sum / n:.3f}")

    if show_failures > 0 and failures:
        print("")
        print(f"Top {min(show_failures, len(failures))} failures:")
        for failure in failures[:show_failures]:
            print(
                f"- {failure['id']}: expected={failure['expected']} predicted={failure['predicted']} | {failure['question']}"
            )


def main() -> None:
    load_dotenv()
    args = parse_args()
    k_values = sorted({int(v.strip()) for v in args.k_values.split(",") if v.strip()})
    if not k_values:
        raise ValueError("At least one valid k value is required.")

    retriever = DocumentRetriever()

    if args.bootstrap:
        bootstrap_eval_set(
            retriever=retriever,
            eval_set_path=args.eval_set,
            expected_per_question=args.expected_per_question,
            top_k=args.top_k,
            max_docs=args.max_docs,
            use_query_rewrite=args.use_query_rewrite,
        )
        return

    samples = load_eval_samples(args.eval_set)
    evaluate(
        retriever=retriever,
        samples=samples,
        top_k=args.top_k,
        max_docs=args.max_docs,
        k_values=k_values,
        use_query_rewrite=args.use_query_rewrite,
        show_failures=args.show_failures,
    )


if __name__ == "__main__":
    main()

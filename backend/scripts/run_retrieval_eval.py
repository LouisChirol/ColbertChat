import json
from pathlib import Path

from app.services.retrieval import DocumentRetriever


def run_eval() -> int:
    script_dir = Path(__file__).parent
    eval_set_path = script_dir / "retrieval_eval_set.json"
    eval_set = json.loads(eval_set_path.read_text(encoding="utf-8"))

    retriever = DocumentRetriever()
    total = len(eval_set)
    hits = 0

    for item in eval_set:
        question = item["question"]
        expected_doc_ids = set(item.get("expected_doc_ids", []))
        docs = retriever.retrieve_documents(question, top_k=20, max_docs=8)
        retrieved_ids = {doc.id for doc in docs if doc.id}
        if retrieved_ids.intersection(expected_doc_ids):
            hits += 1

    score = hits / total if total else 0.0
    print(f"retrieval_eval_total={total}")
    print(f"retrieval_eval_hits={hits}")
    print(f"retrieval_eval_score={score:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_eval())

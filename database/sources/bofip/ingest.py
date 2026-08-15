"""Incremental BOFiP ingestion into a dedicated Chroma collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import backoff
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_mistralai import MistralAIEmbeddings
from loguru import logger
from tqdm import tqdm

load_dotenv()

EMBEDDING_BATCH_SIZE = 20
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 100
BATCH_DELAY_SECONDS = 0.5
MAX_EMBED_RETRIES = 3
MISTRAL_EMBED_USD_PER_M_TOKEN = 0.10

PERSIST_DIR = "chroma_db"
COLLECTION_NAME = "bofip"
TRACKING_DB_PATH = "chroma_db/bofip_tracking.sqlite3"
DEFAULT_RECORDS_DIR = Path("data/bofip/records")


@dataclass
class RecordStatus:
    file_path: Path
    status: str
    previous_chunk_count: int = 0


class RecordTracker:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS document_tracking (
                    file_path TEXT PRIMARY KEY,
                    content_hash TEXT,
                    data_source TEXT,
                    processed_at REAL,
                    chunk_count INTEGER,
                    document_id TEXT
                )
                """
            )
            conn.commit()

    def get_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout = 30000")
            row = conn.execute(
                "SELECT content_hash, data_source, processed_at, chunk_count, document_id "
                "FROM document_tracking WHERE file_path = ?",
                (str(file_path),),
            ).fetchone()
            if row:
                return {
                    "content_hash": row[0],
                    "data_source": row[1],
                    "processed_at": row[2],
                    "chunk_count": int(row[3] or 0),
                    "document_id": row[4],
                }
        return None

    def upsert(
        self,
        file_path: Path,
        content_hash: str,
        data_source: str,
        chunk_count: int,
        document_id: str,
    ) -> None:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute(
                """
                INSERT OR REPLACE INTO document_tracking
                (file_path, content_hash, data_source, processed_at, chunk_count, document_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(file_path),
                    content_hash,
                    data_source,
                    time.time(),
                    chunk_count,
                    document_id,
                ),
            )
            conn.commit()

    def remove(self, file_path: Path) -> None:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute(
                "DELETE FROM document_tracking WHERE file_path = ?", (str(file_path),)
            )
            conn.commit()

    def all_tracked_paths(self) -> List[Path]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout = 30000")
            rows = conn.execute("SELECT file_path FROM document_tracking").fetchall()
        return [Path(row[0]) for row in rows]


class BofipIngestor:
    def __init__(self, records_dir: Path, max_documents: int = -1):
        self.records_dir = records_dir
        if not records_dir.exists():
            raise ValueError(f"Records directory does not exist: {records_dir}")

        self.max_documents = max_documents
        self.tracker = RecordTracker(TRACKING_DB_PATH)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
        )
        self.embeddings = MistralAIEmbeddings(
            model="mistral-embed",
            api_key=os.getenv("MISTRAL_API_KEY"),
            max_retries=MAX_EMBED_RETRIES,
        )
        Path(PERSIST_DIR).mkdir(parents=True, exist_ok=True)
        self.vector_store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=self.embeddings,
            persist_directory=PERSIST_DIR,
        )
        try:
            self.initial_vector_count = int(self.vector_store._collection.count())
        except Exception:
            self.initial_vector_count = 0

    @staticmethod
    def _file_hash(file_path: Path) -> str:
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    def _list_records(self) -> List[Path]:
        files = sorted(self.records_dir.glob("*.json"))
        if self.max_documents > -1:
            files = files[: self.max_documents]
        return files

    @staticmethod
    def _load_record(file_path: Path) -> Dict[str, Any]:
        return json.loads(file_path.read_text(encoding="utf-8"))

    def _parse_and_chunk(
        self, file_path: Path
    ) -> Tuple[List[Dict[str, Any]], int, str, str]:
        record = self._load_record(file_path)
        content = (record.get("contenu") or "").strip()
        document_id = record.get("identifiant_juridique") or file_path.stem
        if not content:
            return [], 0, self._file_hash(file_path), document_id

        title = record.get("titre") or ""
        header = f"{title}\nSérie: {record.get('serie', '')}\nIdentifiant: {document_id}\n\n"
        full_text = header + content
        chunks = self.text_splitter.split_text(full_text)

        metadata_base = {
            "source_id": "bofip",
            "source_name": "bofip",
            "document_id": document_id,
            "canonical_url": record.get("permalien") or "",
            "title": title,
            "serie": record.get("serie") or "",
            "doc_type": record.get("type") or "",
            "effective_date": record.get("debut_de_validite") or "",
            "source_file": str(file_path),
            "data_source": "bofip",
        }

        documents: List[Dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            documents.append(
                {
                    "content": chunk,
                    "metadata": {
                        **metadata_base,
                        "chunk_id": i,
                        "total_chunks": len(chunks),
                    },
                }
            )
        return documents, len(documents), self._file_hash(file_path), document_id

    def estimate_embed_cost(self, files: Iterable[Path]) -> Dict[str, Any]:
        total_chars = 0
        doc_count = 0
        for file_path in files:
            record = self._load_record(file_path)
            content = (record.get("contenu") or "").strip()
            if not content:
                continue
            doc_count += 1
            title = record.get("titre") or ""
            total_chars += len(title) + len(content)

        est_tokens = int(total_chars / 4)
        est_chunks = max(1, int(total_chars / CHUNK_SIZE) + 1) * doc_count // max(doc_count, 1)
        est_cost_usd = (est_tokens / 1_000_000) * MISTRAL_EMBED_USD_PER_M_TOKEN
        return {
            "documents_with_content": doc_count,
            "total_chars": total_chars,
            "estimated_tokens": est_tokens,
            "estimated_chunks": est_chunks,
            "estimated_cost_usd": round(est_cost_usd, 4),
        }

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=MAX_EMBED_RETRIES,
        giveup=lambda e: "429" not in str(e),
    )
    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self.embeddings.embed_documents(texts)

    def _add_documents(self, docs: List[Dict[str, Any]]) -> Tuple[int, int]:
        if not docs:
            return 0, 0
        success = 0
        errors = 0
        file_path = Path(docs[0]["metadata"]["source_file"])
        prefix = hashlib.md5(str(file_path).encode()).hexdigest()[:12]

        for start in range(0, len(docs), EMBEDDING_BATCH_SIZE):
            batch = docs[start : start + EMBEDDING_BATCH_SIZE]
            texts = [d["content"] for d in batch]
            metadatas = [d["metadata"] for d in batch]
            ids = [
                f"bofip_{prefix}_{hashlib.md5(text.encode()).hexdigest()[:12]}_{idx}"
                for idx, text in enumerate(texts)
            ]
            try:
                embeddings = self._embed_batch(texts)
                self.vector_store._collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=texts,
                    metadatas=metadatas,
                )
                success += len(batch)
            except Exception as exc:
                logger.error(f"Failed BOFiP embed batch: {exc}")
                errors += len(batch)
            time.sleep(BATCH_DELAY_SECONDS)
        return success, errors

    def _file_status(self, file_path: Path) -> RecordStatus:
        current_hash = self._file_hash(file_path)
        info = self.tracker.get_info(file_path)
        if not info:
            return RecordStatus(file_path=file_path, status="new")
        if info["content_hash"] != current_hash:
            return RecordStatus(
                file_path=file_path,
                status="updated",
                previous_chunk_count=info["chunk_count"],
            )
        return RecordStatus(
            file_path=file_path,
            status="unchanged",
            previous_chunk_count=info["chunk_count"],
        )

    def _process_file(self, file_path: Path, remove_existing: bool) -> Tuple[int, int, int]:
        docs, chunk_count, content_hash, document_id = self._parse_and_chunk(file_path)
        if remove_existing:
            self.vector_store._collection.delete(where={"source_file": str(file_path)})
        success, errors = self._add_documents(docs)
        self.tracker.upsert(
            file_path=file_path,
            content_hash=content_hash,
            data_source="bofip",
            chunk_count=chunk_count,
            document_id=document_id,
        )
        return success, errors, chunk_count

    def run(self, cleanup_removed: bool = True) -> Dict[str, Any]:
        files = self._list_records()
        if cleanup_removed:
            current = {str(p) for p in files}
            for tracked in self.tracker.all_tracked_paths():
                if str(tracked) not in current:
                    self.vector_store._collection.delete(
                        where={"source_file": str(tracked)}
                    )
                    self.tracker.remove(tracked)

        statuses = [self._file_status(p) for p in files]
        to_process = [s for s in statuses if s.status in {"new", "updated"}]
        unchanged = [s for s in statuses if s.status == "unchanged"]

        logger.info(
            f"BOFiP ingest — new: {len([s for s in statuses if s.status=='new'])}, "
            f"updated: {len([s for s in statuses if s.status=='updated'])}, "
            f"unchanged: {len(unchanged)}, total: {len(files)}"
        )

        embedded_chunks = 0
        for status in tqdm(to_process, desc="Embedding BOFiP"):
            success, _, _ = self._process_file(
                status.file_path, remove_existing=status.status == "updated"
            )
            embedded_chunks += success

        final_count = int(self.vector_store._collection.count())
        baseline = sum(s.previous_chunk_count for s in unchanged) + sum(
            self.tracker.get_info(s.file_path)["chunk_count"]
            for s in to_process
            if self.tracker.get_info(s.file_path)
        )
        savings = 0.0
        if baseline:
            savings = max(0.0, (1 - embedded_chunks / baseline) * 100)

        return {
            "new_files": len([s for s in statuses if s.status == "new"]),
            "updated_files": len([s for s in statuses if s.status == "updated"]),
            "unchanged_files": len(unchanged),
            "embedded_chunks": embedded_chunks,
            "initial_vector_count": self.initial_vector_count,
            "final_vector_count": final_count,
            "compute_savings_percent": round(savings, 1),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest BOFiP records into Chroma")
    parser.add_argument(
        "--records-dir",
        type=Path,
        default=DEFAULT_RECORDS_DIR,
        help="Directory of per-record JSON files",
    )
    parser.add_argument(
        "--max-documents",
        type=int,
        default=-1,
        help="Limit number of records (for pilot embeds)",
    )
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Print embed cost estimate and exit",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=None,
        help="Abort embed if estimated cost exceeds this threshold",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ingestor = BofipIngestor(args.records_dir, max_documents=args.max_documents)
    files = ingestor._list_records()
    estimate = ingestor.estimate_embed_cost(files)
    logger.info(f"BOFiP embed estimate: {estimate}")

    if args.estimate_only:
        print(json.dumps(estimate, indent=2))
        return 0

    if args.max_cost_usd is not None and estimate["estimated_cost_usd"] > args.max_cost_usd:
        logger.error(
            f"Estimated cost ${estimate['estimated_cost_usd']} exceeds "
            f"max ${args.max_cost_usd} — aborting"
        )
        return 1

    result = ingestor.run()
    logger.success(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

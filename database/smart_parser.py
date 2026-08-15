import argparse
import hashlib
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import backoff
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_mistralai import MistralAIEmbeddings
from loguru import logger
from tqdm import tqdm

# Load environment variables
load_dotenv()


# Tunables
EMBEDDING_BATCH_SIZE = 20
MAX_THREADS = 8
MAX_DOCUMENTS = -1  # -1 means no limit
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 100
BATCH_DELAY_SECONDS = 0.5
MAX_EMBED_RETRIES = 3


TRACKING_DB_PATH = (
    "chroma_db/tracking.sqlite3"  # Separate SQLite DB for tracking to avoid conflicts
)
PERSIST_DIR = "chroma_db"
COLLECTION_NAME = "service_public"


@dataclass
class FileStatus:
    file_path: Path
    status: str  # "new" | "updated" | "unchanged"
    previous_chunk_count: int = 0


class DocumentTracker:
    """Tracks processed files to enable precise incremental updates and stats."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tracking_table()

    def _init_tracking_table(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            # Increase busy timeout to reduce 'database is locked' errors
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
            except Exception:
                pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS document_tracking (
                    file_path TEXT PRIMARY KEY,
                    last_modified REAL,
                    content_hash TEXT,
                    data_source TEXT,
                    processed_at REAL,
                    chunk_count INTEGER
                )
                """
            )
            conn.commit()

    def get_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
            except Exception:
                pass
            cursor = conn.execute(
                "SELECT last_modified, content_hash, data_source, processed_at, chunk_count FROM document_tracking WHERE file_path = ?",
                (str(file_path),),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "last_modified": row[0],
                    "content_hash": row[1],
                    "data_source": row[2],
                    "processed_at": row[3],
                    "chunk_count": int(row[4] or 0),
                }
        return None

    def upsert(
        self, file_path: Path, content_hash: str, data_source: str, chunk_count: int
    ) -> None:
        current_time = time.time()
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
            except Exception:
                pass
            conn.execute(
                """
                INSERT OR REPLACE INTO document_tracking
                (file_path, last_modified, content_hash, data_source, processed_at, chunk_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(file_path),
                    file_path.stat().st_mtime,
                    content_hash,
                    data_source,
                    current_time,
                    int(chunk_count),
                ),
            )
            conn.commit()

    def remove(self, file_path: Path) -> None:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
            except Exception:
                pass
            conn.execute(
                "DELETE FROM document_tracking WHERE file_path = ?", (str(file_path),)
            )
            conn.commit()

    def all_tracked_paths(self) -> List[Path]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
            except Exception:
                pass
            cursor = conn.execute("SELECT file_path FROM document_tracking")
            return [Path(row[0]) for row in cursor.fetchall()]


class SmartXMLUpdater:
    """Incremental XML updater that replaces outdated vectors and re-embeds changed files only."""

    def __init__(self, data_dirs: Iterable[str]):
        self.data_dirs: List[Path] = [Path(p) for p in data_dirs]
        self.tracker = DocumentTracker(TRACKING_DB_PATH)

        # Validate input directories and count XML files
        total_xml_files = 0
        for data_dir in self.data_dirs:
            if not data_dir.exists():
                raise ValueError(f"Data directory does not exist: {data_dir}")
            xml_files = list(data_dir.rglob("*.xml"))
            total_xml_files += len(xml_files)
            logger.info(f"Found {len(xml_files)} XML files in {data_dir}")
        if total_xml_files == 0:
            raise ValueError("No XML files found in the provided directories")

        # Text chunking
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
        )

        # Embeddings
        self.embeddings = MistralAIEmbeddings(
            model="mistral-embed",
            api_key=os.getenv("MISTRAL_API_KEY"),
            max_retries=MAX_EMBED_RETRIES,
        )

        # Chroma vector store
        Path(PERSIST_DIR).mkdir(parents=True, exist_ok=True)
        self.vector_store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=self.embeddings,
            persist_directory=PERSIST_DIR,
        )

        # Attempt to read initial vector count; if the collection/index is corrupted,
        # reset the Chroma persistence while preserving the tracking DB.
        def _reset_chroma_preserving_tracker():
            try:
                tracker_path = Path(TRACKING_DB_PATH)
                backup_path = (
                    tracker_path.with_suffix(".bak") if tracker_path.exists() else None
                )
                if backup_path:
                    try:
                        backup_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    tracker_path.replace(backup_path)
                # Wipe chroma persistence
                import shutil

                shutil.rmtree(PERSIST_DIR, ignore_errors=True)
                Path(PERSIST_DIR).mkdir(parents=True, exist_ok=True)
                # Restore tracker if we backed it up
                if backup_path and backup_path.exists():
                    backup_path.replace(tracker_path)
            except Exception as e:
                logger.warning(f"Failed to reset Chroma persistence: {e}")

        try:
            self.initial_vector_count = int(self.vector_store._collection.count())
        except Exception as e:
            logger.error(
                f"Collection count failed ({e}). Attempting to reset Chroma persistence and rebuild."
            )
            _reset_chroma_preserving_tracker()
            # Recreate vector store
            self.vector_store = Chroma(
                collection_name=COLLECTION_NAME,
                embedding_function=self.embeddings,
                persist_directory=PERSIST_DIR,
            )
            self.initial_vector_count = 0
            self._force_rebuild = True
        logger.info(f"Initial vector count: {self.initial_vector_count}")
        # If vectors are empty but tracking exists, we want to force re-embedding unchanged files
        self._force_rebuild = self.initial_vector_count == 0

        self.stats = {
            "new_files": 0,
            "updated_files": 0,
            "unchanged_files": 0,
            "deleted_files": 0,
            "embedded_chunks": 0,
            "baseline_chunks": 0,
        }

    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    def _has_vectors_for_file(self, file_path: Path) -> bool:
        """Return True if at least one vector exists in Chroma for this file.

        Uses a lightweight presence check with limit=1 and no payloads.
        """
        try:
            res = self.vector_store._collection.get(
                where={"source_file": str(file_path)},
                limit=1,
                include=[],
            )
            if isinstance(res, dict):
                ids = res.get("ids", [])
            else:
                ids = getattr(res, "ids", [])
            return bool(ids)
        except Exception as e:
            logger.debug(f"Vector presence check failed for {file_path}: {e}")
            # Be conservative: if uncertain, mark as missing so we re-embed
            return False

    def _file_status(self, file_path: Path) -> FileStatus:
        current_hash = self._compute_file_hash(file_path)
        stored = self.tracker.get_info(file_path)
        if stored is None:
            # Should be seeded before status evaluation; treat as new as a fallback
            return FileStatus(file_path=file_path, status="new", previous_chunk_count=0)
        # If vector store was reset, force re-embed all
        if self._force_rebuild:
            return FileStatus(
                file_path=file_path,
                status="updated",
                previous_chunk_count=int(stored.get("chunk_count", 0)),
            )
        # Only content hash determines change; ignore mtime because extraction updates timestamps
        if stored.get("content_hash") != current_hash:
            return FileStatus(
                file_path=file_path,
                status="updated",
                previous_chunk_count=int(stored.get("chunk_count", 0)),
            )
        # If previously not embedded (seeded with 0 chunks), embed now
        if int(stored.get("chunk_count", 0)) <= 0:
            return FileStatus(
                file_path=file_path,
                status="updated",
                previous_chunk_count=0,
            )
        # If vectors are missing for this file (partial/incomplete store), embed now
        if not self._has_vectors_for_file(file_path):
            return FileStatus(
                file_path=file_path,
                status="updated",
                previous_chunk_count=int(stored.get("chunk_count", 0)),
            )
        # Truly unchanged and present
        return FileStatus(
            file_path=file_path,
            status="unchanged",
            previous_chunk_count=int(stored.get("chunk_count", 0)),
        )

    def _seed_missing_tracker(self, all_files: List[Path]) -> int:
        """Seed tracker entries for files not yet tracked (no embedding), fast path.

        Records content_hash and data_source with chunk_count=0 so future runs can
        detect changes without per-file vector lookups.
        Returns number of files seeded.
        """
        seeded = 0
        for file_path in all_files:
            if self.tracker.get_info(file_path) is not None:
                continue
            try:
                content_hash = self._compute_file_hash(file_path)
                data_source = self._infer_data_source(file_path)
                self.tracker.upsert(
                    file_path=file_path,
                    content_hash=content_hash,
                    data_source=data_source,
                    chunk_count=0,
                )
                seeded += 1
            except Exception as e:
                logger.debug(f"Seeding tracker failed for {file_path}: {e}")
        if seeded:
            logger.info(f"Seeded tracking for {seeded} files (no embedding)")
        return seeded

    @staticmethod
    def _infer_data_source(file_path: Path) -> str:
        path_str = str(file_path)
        if "vosdroits" in path_str:
            return "vosdroits"
        if "entreprendre" in path_str:
            return "entreprendre"
        return "unknown"

    @staticmethod
    def _extract_text_content(element: ET.Element) -> str:
        parts: List[str] = []
        if element.text and element.text.strip():
            parts.append(element.text.strip())
        for child in element:
            child_text = SmartXMLUpdater._extract_text_content(child)
            if child_text:
                parts.append(child_text)
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
        return " ".join(parts)

    @staticmethod
    def _extract_metadata(root: ET.Element) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        for dc_elem in root.findall(".//{http://purl.org/dc/elements/1.1/}*"):
            tag = dc_elem.tag.split("}")[-1]
            metadata[tag] = dc_elem.text
        for attr in root.attrib:
            if attr in ["ID", "type", "spUrl", "dateCreation", "dateMaj"]:
                metadata[attr] = root.attrib[attr]
        return metadata

    def _parse_and_chunk(
        self, file_path: Path
    ) -> Tuple[List[Dict[str, Any]], int, str]:
        tree = ET.parse(file_path)
        root = tree.getroot()

        content = self._extract_text_content(root)
        if not content.strip():
            return [], 0, self._compute_file_hash(file_path)

        metadata = self._extract_metadata(root)
        metadata["source_file"] = str(file_path)
        metadata["data_source"] = self._infer_data_source(file_path)

        chunks = self.text_splitter.split_text(content)
        documents: List[Dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            documents.append(
                {
                    "content": chunk,
                    "metadata": {
                        **metadata,
                        "chunk_id": i,
                        "total_chunks": len(chunks),
                    },
                }
            )

        return documents, len(documents), self._compute_file_hash(file_path)

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

        total_success = 0
        total_errors = 0

        # Build a stable per-file prefix for IDs to avoid collisions across files
        file_path = Path(docs[0]["metadata"]["source_file"]) if docs else None
        file_hash_prefix = (
            hashlib.md5(str(file_path).encode()).hexdigest()[:12]
            if file_path
            else "no_file"
        )

        for start in range(0, len(docs), EMBEDDING_BATCH_SIZE):
            batch = docs[start : start + EMBEDDING_BATCH_SIZE]
            texts = [d["content"] for d in batch]
            metadatas = [d["metadata"] for d in batch]
            ids = [
                f"{file_hash_prefix}_{md5[:12]}_{idx}"
                for idx, md5 in enumerate(
                    [hashlib.md5(text.encode()).hexdigest() for text in texts]
                )
            ]
            try:
                embeddings = self._embed_batch(texts)
                self.vector_store._collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=texts,
                    metadatas=metadatas,
                )
                total_success += len(batch)
            except Exception as e:
                logger.error(f"Failed to add a batch: {e}")
                total_errors += len(batch)

            time.sleep(BATCH_DELAY_SECONDS)

        return total_success, total_errors

    def _process_file(
        self, file_path: Path, remove_existing: bool
    ) -> Tuple[int, int, int]:
        """Process a single file. If remove_existing is True, delete previous vectors first.

        Returns (embedded_count, error_count, current_chunk_count).
        """
        documents, chunk_count, current_hash = self._parse_and_chunk(file_path)

        if remove_existing:
            # Remove old chunks for this file from vector store
            self.vector_store._collection.delete(where={"source_file": str(file_path)})

        success, errors = self._add_documents(documents)
        data_source = self._infer_data_source(file_path)
        self.tracker.upsert(
            file_path=file_path,
            content_hash=current_hash,
            data_source=data_source,
            chunk_count=chunk_count,
        )

        return success, errors, chunk_count

    def _collect_all_xml_files(self) -> List[Path]:
        files: List[Path] = []
        for d in self.data_dirs:
            xmls = list(d.rglob("*.xml"))
            if MAX_DOCUMENTS > -1:
                xmls = xmls[:MAX_DOCUMENTS]
            files.extend(xmls)
        return files

    def cleanup_deleted_files(self) -> int:
        """Delete vectors and tracking entries for files that disappeared from the dataset."""
        current_files_set = {str(p) for p in self._collect_all_xml_files()}
        deleted_count = 0
        for tracked_path in self.tracker.all_tracked_paths():
            if str(tracked_path) not in current_files_set:
                # Remove vectors and tracking for missing file
                logger.info(f"Removing vectors for deleted file: {tracked_path}")
                self.vector_store._collection.delete(
                    where={"source_file": str(tracked_path)}
                )
                self.tracker.remove(tracked_path)
                deleted_count += 1
        return deleted_count

    def run(self, cleanup_removed: bool = True) -> Dict[str, Any]:
        # Optionally cleanup deleted files first
        if cleanup_removed:
            deleted = self.cleanup_deleted_files()
            self.stats["deleted_files"] = deleted

        all_files = self._collect_all_xml_files()
        # Ensure tracker has entries for all files to avoid expensive vector presence checks
        if self.initial_vector_count > 0:
            self._seed_missing_tracker(all_files)
        file_statuses: List[FileStatus] = [self._file_status(p) for p in all_files]

        new_files = [fs for fs in file_statuses if fs.status == "new"]
        updated_files = [fs for fs in file_statuses if fs.status == "updated"]
        unchanged_files = [fs for fs in file_statuses if fs.status == "unchanged"]

        self.stats["new_files"] = len(new_files)
        self.stats["updated_files"] = len(updated_files)
        # Count backfill as unchanged for reporting purposes
        self.stats["unchanged_files"] = len(unchanged_files)

        # Baseline chunks (what would be embedded if we reprocessed everything)
        baseline_chunks = 0
        baseline_chunks += sum(fs.previous_chunk_count for fs in unchanged_files)

        # Preview summary before any embedding begins
        logger.info(
            f"Planned actions — New: {len(new_files)}, Updated: {len(updated_files)}, "
            f"Unchanged (skipped): {len(unchanged_files)}, Total: {len(all_files)}"
        )

        # Process changed files with progress
        total_success = 0
        total_errors = 0
        changed_files = new_files + updated_files

        if not changed_files:
            logger.info("No changed files detected. Nothing to embed.")
        else:
            with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                futures = []
                for fs in changed_files:
                    futures.append(
                        executor.submit(
                            self._process_file, fs.file_path, fs.status == "updated"
                        )
                    )
                for future in tqdm(
                    as_completed(futures),
                    total=len(futures),
                    desc="Embedding changed files",
                ):
                    try:
                        success, errors, chunk_count = future.result()
                        total_success += success
                        total_errors += errors
                        baseline_chunks += chunk_count
                        # Throttle a bit between batches
                        time.sleep(BATCH_DELAY_SECONDS)
                    except Exception as e:
                        logger.error(f"Failed to process a file: {e}")

        # Persist vector store if supported by the integration version
        try:
            persist_method = getattr(self.vector_store, "persist", None)
            if callable(persist_method):
                persist_method()
        except Exception as e:
            logger.debug(f"Vector store persist skipped/failed: {e}")

        self.stats["embedded_chunks"] = total_success
        self.stats["baseline_chunks"] = baseline_chunks

        # Compute savings: 1 - (actual / baseline)
        savings_pct = 0.0
        if baseline_chunks > 0:
            savings_pct = (
                max(0.0, 1.0 - (float(total_success) / float(baseline_chunks))) * 100.0
            )

        final_vector_count = int(self.vector_store._collection.count())

        result = {
            "new_files": self.stats["new_files"],
            "updated_files": self.stats["updated_files"],
            "unchanged_files": self.stats["unchanged_files"],
            "deleted_files": self.stats["deleted_files"],
            "embedded_chunks": total_success,
            "failed_chunks": total_errors,
            "baseline_chunks": baseline_chunks,
            "compute_savings_percent": round(savings_pct, 2),
            "initial_vector_count": self.initial_vector_count,
            "final_vector_count": final_vector_count,
            "vectors_added": max(0, final_vector_count - self.initial_vector_count),
        }

        logger.info(
            " | ".join(
                [
                    f"New: {result['new_files']}",
                    f"Updated: {result['updated_files']}",
                    f"Unchanged: {result['unchanged_files']}",
                    f"Deleted: {result['deleted_files']}",
                    f"Embedded chunks: {result['embedded_chunks']}",
                    f"Failed chunks: {result['failed_chunks']}",
                    f"Baseline chunks: {result['baseline_chunks']}",
                    f"Compute saved: {result['compute_savings_percent']}%",
                    f"Vectors: {result['initial_vector_count']} -> {result['final_vector_count']} (+{result['vectors_added']})",
                ]
            )
        )

        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smart incremental XML parser for ChromaDB"
    )
    parser.add_argument(
        "--data-dirs",
        nargs="+",
        default=[
            "data/service-public/vosdroits-latest",
            "data/service-public/entreprendre-latest",
        ],
        help="Directories containing XML dumps to process",
    )
    parser.add_argument(
        "--no-cleanup-removed",
        action="store_true",
        help="Do not clean vectors/tracking for files removed from the dataset",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    updater = SmartXMLUpdater(data_dirs=args.data_dirs)
    updater.run(cleanup_removed=not args.no_cleanup_removed)


if __name__ == "__main__":
    main()

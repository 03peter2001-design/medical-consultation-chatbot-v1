"""
從 classified_chunks.jsonl 建立 versioned Chroma collections。

執行：
    cd backend
    python -m scripts.ingest --version v2 --dry-run
    python -m scripts.ingest --version v2

此腳本絕不刪除 legacy `medical_kb`。只有明確指定 --rebuild 時，
才會刪除相同 version 的五個目標 collections。
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from knowledge.common import (
    CHROMA_DIR,
    CLASSIFICATION_REPORT,
    CLASSIFIED_CORPUS,
    CLASSIFIED_EMBEDDINGS,
    EMBEDDING_MODEL,
    INDEX_ROUTES,
    MAX_VECTOR_ROWS,
    collection_name,
)

BATCH_SIZE = 64
LEGACY_COLLECTION = "medical_kb"


def load_classified_chunks(
    path: Path = CLASSIFIED_CORPUS,
) -> Iterable[dict]:
    if not path.exists():
        raise RuntimeError(f"找不到分類後語料：{path}\n請先執行 python -m scripts.classify_chunks")

    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path} 第 {line_number} 行不是合法 JSON") from exc
            missing = {
                "chunk_id",
                "article_id",
                "text",
                "routes",
                "route_scores",
            } - record.keys()
            if missing:
                raise RuntimeError(f"{path} 第 {line_number} 行缺少欄位：{sorted(missing)}")
            yield record


def calculate_index_stats(records: Iterable[dict]) -> dict:
    chunk_counts = Counter()
    article_ids = defaultdict(set)
    unique_indexed_chunks = set()
    total_chunks = 0
    archive_chunks = 0

    for record in records:
        total_chunks += 1
        indexed = False
        for route in record["routes"]:
            if route not in INDEX_ROUTES:
                continue
            indexed = True
            chunk_counts[route] += 1
            article_ids[route].add(record["article_id"])
            unique_indexed_chunks.add(record["chunk_id"])
        if not indexed:
            archive_chunks += 1

    vector_rows = sum(chunk_counts.values())
    return {
        "total_chunks": total_chunks,
        "archive_chunks": archive_chunks,
        "unique_indexed_chunks": len(unique_indexed_chunks),
        "vector_rows": vector_rows,
        "duplicate_vector_rows": vector_rows - len(unique_indexed_chunks),
        "max_vector_rows": MAX_VECTOR_ROWS,
        "within_vector_limit": vector_rows <= MAX_VECTOR_ROWS,
        "collections": {
            route: {
                "chunks": chunk_counts[route],
                "articles": len(article_ids[route]),
            }
            for route in INDEX_ROUTES
        },
    }


def load_embedding_store(
    embeddings_path: Path = CLASSIFIED_EMBEDDINGS,
    report_path: Path = CLASSIFICATION_REPORT,
):
    if not report_path.exists() or not embeddings_path.exists():
        return None

    report = json.loads(report_path.read_text(encoding="utf-8"))
    count = int(report.get("embedding_count", 0))
    dimension = int(report.get("embedding_dimension", 0))
    model = report.get("embedding_model")
    if not count or not dimension:
        return None
    if model != EMBEDDING_MODEL:
        raise RuntimeError(f"分類 embedding 模型為 {model}，查詢模型為 {EMBEDDING_MODEL}")

    import numpy as np

    expected_bytes = count * dimension * 4
    actual_bytes = embeddings_path.stat().st_size
    if actual_bytes != expected_bytes:
        raise RuntimeError(f"embedding 檔案大小不符：預期 {expected_bytes}，實際 {actual_bytes}")
    return np.memmap(
        embeddings_path,
        dtype=np.float32,
        mode="r",
        shape=(count, dimension),
    )


def attach_embeddings(records: Iterable[dict], embedding_store):
    for record in records:
        if "embedding_index" in record:
            if embedding_store is None:
                raise RuntimeError("分類語料有 embedding_index，但找不到 embedding 檔")
            index = int(record["embedding_index"])
            if index < 0 or index >= len(embedding_store):
                raise RuntimeError(f"embedding_index 超出範圍：{record['chunk_id']} → {index}")
            record["_embedding"] = embedding_store[index]
        yield record


def _collection_names(client) -> set[str]:
    names = set()
    for item in client.list_collections():
        names.add(item.name if hasattr(item, "name") else str(item))
    return names


def build_collections(
    client,
    records: Iterable[dict],
    version: str,
    embedding_function,
    rebuild: bool = False,
    batch_size: int = BATCH_SIZE,
) -> dict:
    target_names = {route: collection_name(version, route) for route in INDEX_ROUTES}
    existing = _collection_names(client)

    if rebuild:
        for name in target_names.values():
            if name in existing:
                client.delete_collection(name)
    else:
        collisions = sorted(set(target_names.values()) & existing)
        if collisions:
            raise RuntimeError(
                "目標 collections 已存在；若確定要重建，請加 --rebuild：" + ", ".join(collisions)
            )

    if LEGACY_COLLECTION not in existing and rebuild:
        # 明確記錄 invariant；不需要 legacy 存在，但絕不可因 rebuild 建立或刪除它。
        pass

    collections = {
        route: client.create_collection(
            name=name,
            embedding_function=embedding_function,
            metadata={
                "hnsw:space": "cosine",
                "index_version": version,
                "route": route,
            },
        )
        for route, name in target_names.items()
    }
    buffers = {
        route: {
            "documents": [],
            "ids": [],
            "metadatas": [],
            "embeddings": [],
        }
        for route in INDEX_ROUTES
    }
    counts = Counter()

    def flush(route: str) -> None:
        buffer = buffers[route]
        if not buffer["documents"]:
            return
        kwargs = {
            "documents": buffer["documents"],
            "ids": buffer["ids"],
            "metadatas": buffer["metadatas"],
        }
        if buffer["embeddings"]:
            if len(buffer["embeddings"]) != len(buffer["documents"]):
                raise RuntimeError("同一批資料混用了預先計算與即時計算 embedding")
            kwargs["embeddings"] = buffer["embeddings"]
        collections[route].add(**kwargs)
        for values in buffer.values():
            values.clear()

    for record in records:
        for route in record["routes"]:
            if route not in INDEX_ROUTES:
                continue
            buffer = buffers[route]
            buffer["documents"].append(record["text"])
            buffer["ids"].append(record["chunk_id"])
            if record.get("_embedding") is not None:
                buffer["embeddings"].append(record["_embedding"])
            buffer["metadatas"].append(
                {
                    "chunk_id": record["chunk_id"],
                    "article_id": record["article_id"],
                    "title": record.get("title", "")[:200],
                    "url": record.get("url", ""),
                    "updated": record.get("updated", ""),
                    "source": " | ".join(record.get("source_labels", [])),
                    "source_tags": ",".join(record.get("source_tags", [])),
                    "route": route,
                    "primary_route": record.get("primary_route", "archive"),
                    "route_score": float(record.get("route_scores", {}).get(route, 0.0)),
                    "clinical_stage": record.get("clinical_stage", "general"),
                    "safety_tags": ",".join(record.get("safety_tags", [])),
                    "classification_method": record.get("classification_method", ""),
                }
            )
            counts[route] += 1
            if len(buffer["documents"]) >= batch_size:
                flush(route)

    for route in INDEX_ROUTES:
        flush(route)

    return {
        "version": version,
        "collections": {
            route: {
                "name": target_names[route],
                "count": collections[route].count(),
            }
            for route in INDEX_ROUTES
        },
        "vector_rows": sum(counts.values()),
    }


def create_embedding_function():
    from chromadb.utils import embedding_functions

    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        local_files_only=os.getenv("HF_HUB_OFFLINE", "").lower() in {"1", "true", "yes"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="建立 versioned RAG 多 collection 索引")
    parser.add_argument("--version", default="v2")
    parser.add_argument("--input", type=Path, default=CLASSIFIED_CORPUS)
    parser.add_argument(
        "--embeddings",
        type=Path,
        help="預設讀取 --input 相同目錄的 classified_embeddings.f32",
    )
    parser.add_argument(
        "--classification-report",
        type=Path,
        help="預設讀取 --input 相同目錄的 classification_report.json",
    )
    parser.add_argument("--chroma-dir", type=Path, default=CHROMA_DIR)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="只刪除並重建同 version 的目標 collections",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只輸出統計，不載入 embedding 模型、不修改 Chroma",
    )
    args = parser.parse_args()

    # 先驗證 version，即使 dry-run 也不允許產生非法名稱。
    for route in INDEX_ROUTES:
        collection_name(args.version, route)

    embeddings_path = args.embeddings or args.input.with_name(CLASSIFIED_EMBEDDINGS.name)
    classification_report = args.classification_report or args.input.with_name(
        CLASSIFICATION_REPORT.name
    )
    embedding_store = load_embedding_store(
        embeddings_path,
        classification_report,
    )
    records = attach_embeddings(
        load_classified_chunks(args.input),
        embedding_store,
    )
    stats = calculate_index_stats(records)
    stats["reuses_precomputed_embeddings"] = embedding_store is not None
    embedding_dimension = int(embedding_store.shape[1]) if embedding_store is not None else 384
    estimated_bytes = stats["vector_rows"] * embedding_dimension * 4
    stats["embedding_dimension"] = embedding_dimension
    stats["estimated_embedding_bytes"] = estimated_bytes
    stats["estimated_embedding_mib"] = round(
        estimated_bytes / 1024 / 1024,
        2,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["within_vector_limit"]:
        raise RuntimeError(
            f"總向量列數 {stats['vector_rows']} 超過上限 "
            f"{stats['max_vector_rows']}；請提高次要路由門檻後重新分類"
        )
    if args.dry_run:
        print("dry-run 完成：未修改 Chroma")
        return

    import chromadb

    client = chromadb.PersistentClient(path=str(args.chroma_dir))
    result = build_collections(
        client=client,
        records=attach_embeddings(
            load_classified_chunks(args.input),
            embedding_store,
        ),
        version=args.version,
        embedding_function=create_embedding_function(),
        rebuild=args.rebuild,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"完成：legacy `{LEGACY_COLLECTION}` 未被修改")


if __name__ == "__main__":
    main()

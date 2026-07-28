"""RAG 清洗、分類、建庫與查詢共用的常數與切塊函式。"""

from __future__ import annotations

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CHROMA_DIR = BASE_DIR / "chroma_db"
CLEAN_CORPUS = BASE_DIR / "clean_docs" / "medical_articles.jsonl"
CLASSIFIED_DIR = BASE_DIR / "classified_docs"
CLASSIFIED_CORPUS = CLASSIFIED_DIR / "classified_chunks.jsonl"
CLASSIFIED_EMBEDDINGS = CLASSIFIED_DIR / "classified_embeddings.f32"
CLASSIFICATION_REPORT = CLASSIFIED_DIR / "classification_report.json"
REVIEW_QUEUE = CLASSIFIED_DIR / "review_queue.csv"
TAXONOMY_PATH = Path(__file__).resolve().parent / "taxonomy.json"

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_SIZE = 600
CHUNK_OVERLAP = 80
BASELINE_CHUNKS = 40_526
MAX_VECTOR_ROWS = 50_658

SYMPTOM_ROUTES = ("chest", "headache", "abdomen")
INDEX_ROUTES = ("chest", "headache", "abdomen", "common", "safety")
ALL_ROUTES = INDEX_ROUTES + ("archive",)
CLINICAL_STAGES = (
    "diagnosis",
    "workup",
    "lab",
    "imaging",
    "treatment",
    "general",
)


def collection_name(version: str, route: str) -> str:
    if route not in INDEX_ROUTES:
        raise ValueError(f"不支援的 RAG route：{route}")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", version):
        raise ValueError("version 只能使用小寫英數字與底線，且須以字母開頭")
    return f"medical_{version}_{route}"


def chunk_text(text: str) -> list[str]:
    """
    以空白邊界切成固定字元大小，只在真正完成 chunk 時保留一次 overlap。
    """
    words = re.findall(r"\S+", text)
    if not words:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for word in words:
        added_length = len(word) + (1 if current else 0)
        if current and current_length + added_length > CHUNK_SIZE:
            chunk = " ".join(current)
            if len(chunk) > 60:
                chunks.append(chunk)

            overlap_words: list[str] = []
            overlap_length = 0
            for previous_word in reversed(current):
                candidate_length = len(previous_word) + (1 if overlap_words else 0) + overlap_length
                if candidate_length > CHUNK_OVERLAP:
                    break
                overlap_words.append(previous_word)
                overlap_length = candidate_length

            current = list(reversed(overlap_words))
            current_length = len(" ".join(current))

        current.append(word)
        current_length += len(word) + (1 if len(current) > 1 else 0)

    final_chunk = " ".join(current)
    if len(final_chunk) > 60:
        chunks.append(final_chunk)
    return chunks

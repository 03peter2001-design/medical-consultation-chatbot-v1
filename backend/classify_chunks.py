"""
將清洗後文章切成 chunk，使用規則與語意向量進行多標籤分類。

執行：
    cd backend
    python classify_chunks.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rag_common import (
    CLASSIFICATION_REPORT,
    CLASSIFIED_CORPUS,
    CLASSIFIED_EMBEDDINGS,
    CLEAN_CORPUS,
    EMBEDDING_MODEL,
    INDEX_ROUTES,
    REVIEW_QUEUE,
    SYMPTOM_ROUTES,
    TAXONOMY_PATH,
    chunk_text,
)


@dataclass(frozen=True)
class ClassificationResult:
    primary_route: str
    routes: list[str]
    route_scores: dict[str, float]
    clinical_stage: str
    safety_tags: list[str]
    classification_method: str
    review_required: bool
    review_reasons: list[str]


def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict:
    with path.open(encoding="utf-8") as stream:
        taxonomy = json.load(stream)
    required = {"routes", "safety_rules", "clinical_stage_keywords"}
    missing = required - taxonomy.keys()
    if missing:
        raise ValueError(f"taxonomy 缺少欄位：{sorted(missing)}")
    return taxonomy


def iter_clean_articles(path: Path = CLEAN_CORPUS) -> Iterable[dict]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path} 第 {line_number} 行不是合法 JSON"
                ) from exc


def iter_chunks(path: Path = CLEAN_CORPUS) -> Iterable[dict]:
    for article in iter_clean_articles(path):
        for local_index, text in enumerate(chunk_text(article["text"])):
            yield {
                "chunk_id": f"{article['id']}_{local_index}",
                "article_id": article["id"],
                "title": article["title"],
                "url": article["url"],
                "updated": article.get("updated", ""),
                "source_tags": article.get("source_tags", []),
                "source_labels": article.get("source_labels", []),
                "text": text,
            }


def _keyword_matches(text: str, keywords: list[str]) -> list[str]:
    folded = text.casefold()
    return [keyword for keyword in keywords if keyword.casefold() in folded]


def rule_scores(title: str, text: str, taxonomy: dict) -> dict[str, float]:
    scores: dict[str, float] = {}
    for route, definition in taxonomy["routes"].items():
        title_matches = _keyword_matches(title, definition["keywords"])
        body_matches = _keyword_matches(text, definition["keywords"])
        # 標題命中代表整篇主題，權重高於正文偶然提及。
        weighted_hits = 2 * len(title_matches) + len(body_matches)
        scores[route] = round(min(1.0, weighted_hits / 3), 4)
    return scores


def detect_safety_tags(title: str, text: str, taxonomy: dict) -> list[str]:
    combined = f"{title} {text}".casefold()
    return sorted(
        tag
        for tag, phrases in taxonomy["safety_rules"].items()
        if any(phrase.casefold() in combined for phrase in phrases)
    )


def detect_clinical_stage(title: str, text: str, taxonomy: dict) -> str:
    combined = f"{title} {text}".casefold()
    # 越專門的內容優先；general 是沒有明確階段時的保守預設。
    for stage in ("lab", "imaging", "treatment", "diagnosis", "workup"):
        if any(
            keyword.casefold() in combined
            for keyword in taxonomy["clinical_stage_keywords"][stage]
        ):
            return stage
    return "general"


def classify_chunk(
    chunk: dict,
    taxonomy: dict,
    semantic_scores: dict[str, float] | None = None,
) -> ClassificationResult:
    rules = rule_scores(chunk["title"], chunk["text"], taxonomy)
    semantic_scores = semantic_scores or {}
    scores = {
        route: round(max(rules.get(route, 0.0), semantic_scores.get(route, 0.0)), 4)
        for route in taxonomy["routes"]
    }
    safety_tags = detect_safety_tags(chunk["title"], chunk["text"], taxonomy)
    stage = detect_clinical_stage(chunk["title"], chunk["text"], taxonomy)
    scores["safety"] = 1.0 if safety_tags else 0.0

    symptom_ranked = sorted(
        ((route, scores.get(route, 0.0)) for route in SYMPTOM_ROUTES),
        key=lambda item: (-item[1], item[0]),
    )
    semantic_threshold = taxonomy["semantic_threshold"]
    primary_route = "archive"
    routes: list[str] = []

    if symptom_ranked[0][1] >= semantic_threshold:
        primary_route = symptom_ranked[0][0]
        routes.append(primary_route)
        second_route, second_score = symptom_ranked[1]
        if (
            second_score >= taxonomy["secondary_threshold"]
            and symptom_ranked[0][1] - second_score
            <= taxonomy["secondary_margin"]
        ):
            routes.append(second_route)
    elif scores.get("common", 0.0) >= semantic_threshold:
        primary_route = "common"
        routes.append("common")

    if (
        primary_route in SYMPTOM_ROUTES
        and scores.get("common", 0.0) >= taxonomy["secondary_threshold"]
        and len(routes) < 2
    ):
        routes.append("common")

    # safety 只使用明確規則，不使用向量相似度。
    if safety_tags:
        routes.append("safety")
    routes = list(dict.fromkeys(routes))

    if not routes:
        routes = ["archive"]
        primary_route = "archive"

    used_rule = any(value > 0 for value in rules.values())
    used_semantic = any(value > 0 for value in semantic_scores.values())
    if primary_route == "archive":
        method = "archive"
    elif used_rule and used_semantic:
        method = "hybrid"
    elif used_semantic:
        method = "embedding"
    else:
        method = "rule"

    review_reasons = []
    primary_score = scores.get(primary_route, 0.0)
    if safety_tags:
        review_reasons.append("safety_candidate")
    if primary_route != "archive" and primary_score < taxonomy["low_confidence_threshold"]:
        review_reasons.append("low_confidence")
    if len([route for route in routes if route in SYMPTOM_ROUTES]) > 1:
        review_reasons.append("ambiguous_routes")

    return ClassificationResult(
        primary_route=primary_route,
        routes=routes,
        route_scores={route: scores.get(route, 0.0) for route in INDEX_ROUTES},
        clinical_stage=stage,
        safety_tags=safety_tags,
        classification_method=method,
        review_required=bool(review_reasons),
        review_reasons=review_reasons,
    )


class SemanticScorer:
    def __init__(self, taxonomy: dict, model_name: str = EMBEDDING_MODEL):
        from sentence_transformers import SentenceTransformer

        offline = os.getenv("HF_HUB_OFFLINE", "").lower() in {
            "1",
            "true",
            "yes",
        }
        self.model = SentenceTransformer(
            model_name,
            local_files_only=offline,
        )
        self.routes = list(taxonomy["routes"])
        self.prototype_embeddings = {}
        for route in self.routes:
            prototypes = taxonomy["routes"][route]["prototypes"]
            self.prototype_embeddings[route] = self.model.encode(
                prototypes,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

    def score_batch(
        self, chunks: list[dict]
    ) -> tuple[list[dict[str, float]], list]:
        import numpy as np

        # 同一向量後續會直接寫入 Chroma，因此必須涵蓋完整 chunk；
        # 標題一併加入，讓段落在跨文章檢索時保有主題語境。
        texts = [
            f"{chunk['title']} {chunk['text']}"
            for chunk in chunks
        ]
        embeddings = self.model.encode(
            texts,
            batch_size=128,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        results = []
        for embedding in embeddings:
            route_scores = {}
            for route, prototypes in self.prototype_embeddings.items():
                route_scores[route] = round(
                    float(np.max(prototypes @ embedding)),
                    4,
                )
            results.append(route_scores)
        return results, embeddings


def _write_outputs(
    records: Iterable[dict],
    output_path: Path,
    embeddings_path: Path,
    report_path: Path,
    review_path: Path,
    taxonomy_path: Path,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    embeddings_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)

    route_counts = Counter()
    primary_counts = Counter()
    stage_counts = Counter()
    method_counts = Counter()
    review_counts = Counter()
    article_ids = defaultdict(set)
    unique_indexed_chunks = set()
    sample_heaps: dict[str, list[tuple[int, str, dict]]] = {
        route: [] for route in (*SYMPTOM_ROUTES, "common")
    }
    review_ids = set()
    total = 0
    vector_rows = 0

    output_tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    embeddings_tmp = embeddings_path.with_suffix(
        embeddings_path.suffix + ".tmp"
    )
    review_tmp = review_path.with_suffix(review_path.suffix + ".tmp")
    report_tmp = report_path.with_suffix(report_path.suffix + ".tmp")

    with (
        output_tmp.open("w", encoding="utf-8", newline="\n") as output,
        embeddings_tmp.open("wb") as embeddings_stream,
        review_tmp.open("w", encoding="utf-8", newline="") as review_stream,
    ):
        review_writer = csv.DictWriter(
            review_stream,
            fieldnames=(
                "chunk_id",
                "title",
                "primary_route",
                "routes",
                "route_scores",
                "safety_tags",
                "review_reasons",
                "url",
                "text_preview",
            ),
        )
        review_writer.writeheader()

        embedding_count = 0
        embedding_dimension = 0
        for record in records:
            record = dict(record)
            embedding = record.pop("_embedding", None)
            is_indexed = any(
                route in INDEX_ROUTES for route in record["routes"]
            )
            if embedding is not None and is_indexed:
                import numpy as np

                vector = np.asarray(embedding, dtype=np.float32)
                if embedding_dimension == 0:
                    embedding_dimension = int(vector.shape[0])
                elif vector.shape != (embedding_dimension,):
                    raise ValueError("分類 embedding 維度不一致")
                record["embedding_index"] = embedding_count
                embeddings_stream.write(vector.tobytes(order="C"))
                embedding_count += 1
            total += 1
            primary_counts[record["primary_route"]] += 1
            stage_counts[record["clinical_stage"]] += 1
            method_counts[record["classification_method"]] += 1
            for route in record["routes"]:
                route_counts[route] += 1
                article_ids[route].add(record["article_id"])
                if route != "archive":
                    vector_rows += 1
                    unique_indexed_chunks.add(record["chunk_id"])
            for reason in record["review_reasons"]:
                review_counts[reason] += 1
            sample_route = record["primary_route"]
            if sample_route in sample_heaps:
                sample_key = int(
                    hashlib.sha256(
                        record["chunk_id"].encode("utf-8")
                    ).hexdigest(),
                    16,
                )
                heap = sample_heaps[sample_route]
                candidate = (-sample_key, record["chunk_id"], record)
                if len(heap) < 50:
                    heapq.heappush(heap, candidate)
                elif sample_key < -heap[0][0]:
                    heapq.heapreplace(heap, candidate)

            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            output.write("\n")

            if record["review_required"]:
                review_ids.add(record["chunk_id"])
                review_writer.writerow(
                    {
                        "chunk_id": record["chunk_id"],
                        "title": record["title"],
                        "primary_route": record["primary_route"],
                        "routes": ",".join(record["routes"]),
                        "route_scores": json.dumps(
                            record["route_scores"],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "safety_tags": ",".join(record["safety_tags"]),
                        "review_reasons": ",".join(record["review_reasons"]),
                        "url": record["url"],
                        "text_preview": record["text"][:300],
                    }
                )
            if total % 1000 == 0:
                print(f"已分類 {total} chunks", flush=True)

        for route, heap in sample_heaps.items():
            for _, _, record in sorted(
                heap, key=lambda item: (-item[0], item[1])
            ):
                if record["chunk_id"] in review_ids:
                    continue
                review_counts["route_sample"] += 1
                review_writer.writerow(
                    {
                        "chunk_id": record["chunk_id"],
                        "title": record["title"],
                        "primary_route": record["primary_route"],
                        "routes": ",".join(record["routes"]),
                        "route_scores": json.dumps(
                            record["route_scores"],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "safety_tags": ",".join(record["safety_tags"]),
                        "review_reasons": "route_sample",
                        "url": record["url"],
                        "text_preview": record["text"][:300],
                    }
                )

    report = {
        "schema_version": 1,
        "taxonomy": str(taxonomy_path),
        "embedding_file": str(embeddings_path),
        "embedding_model": EMBEDDING_MODEL if embedding_count else None,
        "embedding_count": embedding_count,
        "embedding_dimension": embedding_dimension,
        "total_chunks": total,
        "vector_rows": vector_rows,
        "duplicate_vector_rows": max(
            0, vector_rows - len(unique_indexed_chunks)
        ),
        "route_chunk_counts": dict(sorted(route_counts.items())),
        "route_article_counts": {
            route: len(ids) for route, ids in sorted(article_ids.items())
        },
        "primary_route_counts": dict(sorted(primary_counts.items())),
        "clinical_stage_counts": dict(sorted(stage_counts.items())),
        "classification_method_counts": dict(sorted(method_counts.items())),
        "review_reason_counts": dict(sorted(review_counts.items())),
    }
    report_tmp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    embeddings_tmp.replace(embeddings_path)
    review_tmp.replace(review_path)
    output_tmp.replace(output_path)
    # report 最後切換，作為三個分類產物已完整寫入的完成標記。
    report_tmp.replace(report_path)
    return report


def classify_corpus(
    input_path: Path = CLEAN_CORPUS,
    output_path: Path = CLASSIFIED_CORPUS,
    embeddings_path: Path = CLASSIFIED_EMBEDDINGS,
    report_path: Path = CLASSIFICATION_REPORT,
    review_path: Path = REVIEW_QUEUE,
    taxonomy_path: Path = TAXONOMY_PATH,
    use_semantic: bool = True,
    batch_size: int = 512,
) -> dict:
    taxonomy = load_taxonomy(taxonomy_path)
    scorer = SemanticScorer(taxonomy) if use_semantic else None

    def classified_records():
        batch: list[dict] = []
        for chunk in iter_chunks(input_path):
            batch.append(chunk)
            if len(batch) >= batch_size:
                yield from classify_batch(batch)
                batch.clear()
        if batch:
            yield from classify_batch(batch)

    def classify_batch(batch: list[dict]):
        if scorer:
            semantic_batch, embeddings = scorer.score_batch(batch)
        else:
            semantic_batch = [{} for _ in batch]
            embeddings = [None for _ in batch]
        for chunk, semantic_scores, embedding in zip(
            batch, semantic_batch, embeddings
        ):
            result = classify_chunk(chunk, taxonomy, semantic_scores)
            yield {
                **chunk,
                "primary_route": result.primary_route,
                "routes": result.routes,
                "route_scores": result.route_scores,
                "clinical_stage": result.clinical_stage,
                "safety_tags": result.safety_tags,
                "classification_method": result.classification_method,
                "review_required": result.review_required,
                "review_reasons": result.review_reasons,
                "_embedding": embedding,
            }

    return _write_outputs(
        classified_records(),
        output_path,
        embeddings_path,
        report_path,
        review_path,
        taxonomy_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="建立 RAG chunk 多標籤分類產物")
    parser.add_argument("--input", type=Path, default=CLEAN_CORPUS)
    parser.add_argument("--output", type=Path, default=CLASSIFIED_CORPUS)
    parser.add_argument(
        "--embeddings",
        type=Path,
        help="預設輸出至 --output 相同目錄",
    )
    parser.add_argument("--report", type=Path, default=CLASSIFICATION_REPORT)
    parser.add_argument("--review-queue", type=Path, default=REVIEW_QUEUE)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help="只執行規則分類，供快速工程 dry-run 使用",
    )
    args = parser.parse_args()

    report = classify_corpus(
        input_path=args.input,
        output_path=args.output,
        embeddings_path=(
            args.embeddings
            or args.output.with_name(CLASSIFIED_EMBEDDINGS.name)
        ),
        report_path=args.report,
        review_path=args.review_queue,
        taxonomy_path=args.taxonomy,
        use_semantic=not args.no_semantic,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

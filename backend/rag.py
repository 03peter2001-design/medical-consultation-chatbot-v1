"""Versioned 多 collection RAG、動態路由與 legacy fallback。"""

from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from rag_common import (
    CHROMA_DIR,
    EMBEDDING_MODEL,
    INDEX_ROUTES,
    SYMPTOM_ROUTES,
    TAXONOMY_PATH,
    collection_name,
)
from rag_translation import get_query_normalizer, get_translation_status


LOGGER = logging.getLogger("rag")
LEGACY_COLLECTION = "medical_kb"
RAG_INDEX_VERSION = os.getenv("RAG_INDEX_VERSION", "legacy").strip().lower()
DISTANCE_THRESHOLD = float(os.getenv("RAG_DISTANCE_THRESHOLD", "0.6"))
PER_COLLECTION_K = 4
RRF_K = 60

QUERY_ROUTE_KEYWORDS = {
    "chest": (
        "chest",
        "cardiac",
        "heart",
        "dyspnea",
        "palpitation",
        "胸",
        "心臟",
        "呼吸困難",
        "心悸",
    ),
    "headache": (
        "headache",
        "migraine",
        "stroke",
        "neurologic",
        "intracranial",
        "頭痛",
        "偏頭痛",
        "中風",
        "神經",
    ),
    "abdomen": (
        "abdominal",
        "abdomen",
        "gastrointestinal",
        "appendicitis",
        "肚子",
        "腹痛",
        "腸胃",
        "闌尾",
    ),
    "common": (
        "laboratory",
        "blood test",
        "medication",
        "allergy",
        "pregnancy",
        "抽血",
        "檢驗",
        "用藥",
        "過敏",
        "懷孕",
    ),
}

PURPOSE_QUERY_TERMS = {
    "diagnosis": "diagnosis red flags",
    "workup": "clinical workup physical examination",
    "lab": "laboratory blood urine test",
    "imaging": "imaging radiograph CT MRI ultrasound",
    "treatment": "treatment management",
    "general": "",
}
ROUTE_QUERY_TERMS = {
    "chest": "chest pain chest discomfort cardiopulmonary",
    "headache": "headache neurologic",
    "abdomen": "abdominal pain acute abdomen",
}
QUERY_EXPANSION_RULES = (
    (("胸", "冒冷汗"), "acute coronary syndrome myocardial infarction"),
    (("胸", "撕裂"), "aortic dissection"),
    (("胸", "血氧"), "pulmonary embolism tension pneumothorax"),
    (("胸", "呼吸困難"), "pulmonary embolism pneumothorax"),
    (("肺栓塞",), "pulmonary embolism"),
    (("氣胸",), "pneumothorax"),
    (("心包膜炎",), "pericarditis"),
    (("雷擊",), "thunderclap headache subarachnoid hemorrhage"),
    (("最嚴重", "頭痛"), "thunderclap headache subarachnoid hemorrhage"),
    (("頭痛", "頸部僵硬"), "bacterial meningitis encephalitis"),
    (("頭痛", "單側"), "acute ischemic stroke focal neurologic deficit"),
    (("頭痛", "失語"), "acute ischemic stroke focal neurologic deficit"),
    (("顳", "頭痛"), "giant cell arteritis temporal arteritis"),
    (("頭部外傷",), "head injury intracranial hemorrhage"),
    (("免疫低下", "頭痛"), "meningitis encephalitis"),
    (("視乳頭水腫",), "papilledema increased intracranial pressure"),
    (("肚臍", "右下腹"), "appendicitis migratory abdominal pain"),
    (("右上腹", "發燒"), "cholecystitis cholangitis"),
    (("腹痛", "背部"), "pancreatitis abdominal aortic aneurysm"),
    (("停止排氣",), "bowel obstruction"),
    (("月經過期",), "ectopic pregnancy"),
    (("血尿",), "renal colic urolithiasis"),
    (("血便", "低血壓"), "gastrointestinal bleeding mesenteric ischemia"),
    (("腹部僵硬",), "bowel perforation peritonitis mesenteric ischemia"),
    (("高燒", "低血壓"), "sepsis septic shock"),
    (("呼吸深快", "糖尿病"), "diabetic ketoacidosis"),
)


@lru_cache(maxsize=1)
def _taxonomy() -> dict:
    with TAXONOMY_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


class CollectionRegistry:
    def __init__(self, chroma_dir: Path = CHROMA_DIR):
        self.chroma_dir = Path(chroma_dir)
        self._client = None
        self._embedding_function = None
        self._collections: dict[str, object] = {}

    @property
    def client(self):
        if self._client is None:
            import chromadb

            self._client = chromadb.PersistentClient(
                path=str(self.chroma_dir)
            )
        return self._client

    @property
    def embedding_function(self):
        if self._embedding_function is None:
            from chromadb.utils import embedding_functions

            self._embedding_function = (
                embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=EMBEDDING_MODEL,
                    local_files_only=os.getenv(
                        "HF_HUB_OFFLINE", ""
                    ).lower()
                    in {"1", "true", "yes"},
                )
            )
        return self._embedding_function

    def list_names(self) -> set[str]:
        if not self.chroma_dir.exists():
            return set()
        names = set()
        for item in self.client.list_collections():
            names.add(item.name if hasattr(item, "name") else str(item))
        return names

    def get(self, route: str | None = None, version: str | None = None):
        version = version or RAG_INDEX_VERSION
        if version == "legacy":
            name = LEGACY_COLLECTION
        else:
            if route not in INDEX_ROUTES:
                raise ValueError(f"v2 查詢需要有效 route：{route}")
            name = collection_name(version, route)

        if name not in self._collections:
            self._collections[name] = self.client.get_collection(
                name=name,
                embedding_function=self.embedding_function,
            )
        return self._collections[name]


_registry = CollectionRegistry()


def _get_collection(route: str | None = None):
    """保留舊程式使用的載入介面。"""
    if RAG_INDEX_VERSION == "legacy":
        return _registry.get(version="legacy")
    return _registry.get(route=route or "common")


def get_rag_status() -> dict:
    names = _registry.list_names()
    if RAG_INDEX_VERSION == "legacy":
        enabled = LEGACY_COLLECTION in names
        active_routes = ["legacy"] if enabled else []
    else:
        active_routes = [
            route
            for route in INDEX_ROUTES
            if collection_name(RAG_INDEX_VERSION, route) in names
        ]
        enabled = all(route in active_routes for route in INDEX_ROUTES)
    status = {
        "enabled": enabled,
        "index_version": RAG_INDEX_VERSION,
        "collections": active_routes,
        "legacy_available": LEGACY_COLLECTION in names,
    }
    status["query_translation"] = get_translation_status()
    return status


def _flatten_patient_data(patient_data: dict | None) -> str:
    if not patient_data:
        return ""
    values = []
    for value in patient_data.values():
        if isinstance(value, (str, int, float)):
            values.append(str(value))
        elif isinstance(value, list):
            values.extend(str(item) for item in value)
    return " ".join(values)


def _expand_query_terms(
    query: str,
    patient_data: dict | None = None,
) -> str:
    combined = " ".join(
        part
        for part in (query, _flatten_patient_data(patient_data))
        if part
    ).casefold()
    expansions = [
        expansion
        for required_terms, expansion in QUERY_EXPANSION_RULES
        if all(term.casefold() in combined for term in required_terms)
    ]
    return " ".join(dict.fromkeys(expansions))


def _rule_route_scores(text: str) -> dict[str, float]:
    folded = text.casefold()
    scores = {}
    for route, keywords in QUERY_ROUTE_KEYWORDS.items():
        hits = sum(keyword.casefold() in folded for keyword in keywords)
        scores[route] = min(1.0, hits / 2)
    return scores


def select_routes(
    query: str,
    primary_route: str | None = None,
    patient_data: dict | None = None,
    purpose: str = "general",
    semantic_scores: dict[str, float] | None = None,
) -> list[str]:
    """
    回傳最多兩個內容 routes 加固定 safety；不記錄或輸出原始病人文字。
    """
    if purpose not in PURPOSE_QUERY_TERMS:
        purpose = "general"
    primary_route = (
        primary_route if primary_route in SYMPTOM_ROUTES else None
    )
    combined = " ".join(
        part for part in (query, _flatten_patient_data(patient_data)) if part
    )
    rule_scores = _rule_route_scores(combined)
    semantic_scores = semantic_scores or {}
    scores = {
        route: max(rule_scores.get(route, 0.0), semantic_scores.get(route, 0.0))
        for route in (*SYMPTOM_ROUTES, "common")
    }

    content_routes: list[str] = []
    if primary_route:
        content_routes.append(primary_route)
        supplements = sorted(
            (
                (route, score)
                for route, score in scores.items()
                if route != primary_route and score >= 0.5
            ),
            key=lambda item: (-item[1], item[0]),
        )
        if purpose in {"lab", "workup"} and "common" not in content_routes:
            content_routes.append("common")
        elif supplements:
            content_routes.append(supplements[0][0])
    else:
        ranked = sorted(
            (
                (route, score)
                for route, score in scores.items()
                if score >= 0.42
            ),
            key=lambda item: (-item[1], item[0]),
        )
        content_routes.extend(route for route, _ in ranked[:2])
        if not content_routes:
            content_routes.append("common")

    # 最多兩個內容庫，再固定加入安全庫。
    content_routes = list(dict.fromkeys(content_routes))[:2]
    return [*content_routes, "safety"]


_prototype_embeddings: dict[str, list] | None = None


def _semantic_route_scores(
    query: str,
    query_embedding=None,
) -> dict[str, float]:
    global _prototype_embeddings

    import numpy as np

    taxonomy = _taxonomy()
    ef = _registry.embedding_function
    if _prototype_embeddings is None:
        _prototype_embeddings = {}
        for route in (*SYMPTOM_ROUTES, "common"):
            _prototype_embeddings[route] = ef(
                input=taxonomy["routes"][route]["prototypes"]
            )

    if query_embedding is None:
        query_embedding = ef(input=[query])[0]
    query_embedding = np.asarray(query_embedding, dtype=float)
    query_norm = np.linalg.norm(query_embedding) or 1.0
    scores = {}
    for route, embeddings in _prototype_embeddings.items():
        route_scores = []
        for embedding in embeddings:
            candidate = np.asarray(embedding, dtype=float)
            denominator = (np.linalg.norm(candidate) or 1.0) * query_norm
            route_scores.append(float(candidate @ query_embedding / denominator))
        scores[route] = max(route_scores)
    return scores


def _query_collection(
    route: str,
    query: str,
    n_results: int = PER_COLLECTION_K,
    query_embedding=None,
) -> tuple[list[dict], float]:
    started = time.perf_counter()
    collection = _registry.get(route=route)
    count = collection.count()
    if count == 0:
        return [], time.perf_counter() - started

    query_kwargs = (
        {"query_embeddings": [query_embedding]}
        if query_embedding is not None
        else {"query_texts": [query]}
    )
    results = collection.query(
        **query_kwargs,
        n_results=min(n_results, count),
        include=["documents", "metadatas", "distances"],
    )
    retrieved = []
    for rank, (document, metadata, distance) in enumerate(
        zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ),
        start=1,
    ):
        if distance > DISTANCE_THRESHOLD:
            continue
        retrieved.append(
            {
                "text": document,
                "source": metadata.get("source", ""),
                "title": metadata.get("title", ""),
                "url": metadata.get("url", ""),
                "distance": round(float(distance), 4),
                "chunk_id": metadata.get("chunk_id", ""),
                "article_id": metadata.get("article_id", ""),
                "clinical_stage": metadata.get(
                    "clinical_stage", "general"
                ),
                "route": route,
                "rank": rank,
            }
        )
    return retrieved, time.perf_counter() - started


def _query_collection_variants(
    route: str,
    query_embeddings: list,
    query_variants: list[str],
    n_results: int = PER_COLLECTION_K,
) -> tuple[list[list[dict]], float]:
    """在一次 Chroma 呼叫中批次查詢中文原文與英文正規化向量。"""
    if len(query_embeddings) != len(query_variants):
        raise ValueError("query embeddings and variants must have equal length")

    started = time.perf_counter()
    collection = _registry.get(route=route)
    count = collection.count()
    if count == 0:
        return [[] for _ in query_embeddings], time.perf_counter() - started

    results = collection.query(
        query_embeddings=query_embeddings,
        n_results=min(n_results, count),
        include=["documents", "metadatas", "distances"],
    )
    result_sets = []
    for index, variant in enumerate(query_variants):
        retrieved = []
        for rank, (document, metadata, distance) in enumerate(
            zip(
                results["documents"][index],
                results["metadatas"][index],
                results["distances"][index],
            ),
            start=1,
        ):
            if distance > DISTANCE_THRESHOLD:
                continue
            retrieved.append(
                {
                    "text": document,
                    "source": metadata.get("source", ""),
                    "title": metadata.get("title", ""),
                    "url": metadata.get("url", ""),
                    "distance": round(float(distance), 4),
                    "chunk_id": metadata.get("chunk_id", ""),
                    "article_id": metadata.get("article_id", ""),
                    "clinical_stage": metadata.get(
                        "clinical_stage", "general"
                    ),
                    "route": route,
                    "rank": rank,
                    "query_variant": variant,
                }
            )
        result_sets.append(retrieved)
    return result_sets, time.perf_counter() - started


def _legacy_retrieve(query: str, final_k: int) -> list[dict]:
    try:
        collection = _registry.get(version="legacy")
    except Exception:
        return []
    count = collection.count()
    if count == 0:
        return []
    results = collection.query(
        query_texts=[query],
        n_results=min(final_k, count),
        include=["documents", "metadatas", "distances"],
    )
    retrieved = []
    for rank, (document, metadata, distance) in enumerate(
        zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ),
        start=1,
    ):
        if distance > DISTANCE_THRESHOLD:
            continue
        retrieved.append(
            {
                "text": document,
                "source": metadata.get("source", ""),
                "title": metadata.get("title", ""),
                "url": metadata.get("url", ""),
                "distance": round(float(distance), 4),
                "chunk_id": metadata.get("chunk_id", ""),
                "article_id": metadata.get(
                    "article_id", metadata.get("url", "")
                ),
                "clinical_stage": metadata.get(
                    "clinical_stage", "general"
                ),
                "route": "legacy",
                "rank": rank,
            }
        )
    return retrieved


def _rrf_merge(
    result_sets: Iterable[list[dict]],
    final_k: int,
    route_weights: dict[str, float] | None = None,
) -> list[dict]:
    route_weights = route_weights or {}
    merged: dict[str, dict] = {}
    for results in result_sets:
        for item in results:
            identity = item["chunk_id"] or (
                f"{item['url']}::{item['text'][:100]}"
            )
            score = route_weights.get(item["route"], 1.0) / (
                RRF_K + item.get("rank", 1)
            )
            if identity not in merged:
                merged[identity] = {
                    **item,
                    "routes": [item["route"]],
                    "query_variants": (
                        [item["query_variant"]]
                        if item.get("query_variant")
                        else []
                    ),
                    "rrf_score": score,
                }
            else:
                merged[identity]["rrf_score"] += score
                if item["route"] not in merged[identity]["routes"]:
                    merged[identity]["routes"].append(item["route"])
                query_variant = item.get("query_variant")
                if (
                    query_variant
                    and query_variant not in merged[identity]["query_variants"]
                ):
                    merged[identity]["query_variants"].append(query_variant)
                if item["distance"] < merged[identity]["distance"]:
                    merged[identity]["distance"] = item["distance"]

    ranked = sorted(
        merged.values(),
        key=lambda item: (-item["rrf_score"], item["distance"]),
    )
    article_counts: dict[str, int] = {}
    selected = []
    for item in ranked:
        article_id = item["article_id"] or item["url"] or item["title"]
        article_limit = 1 if "safety" in item["routes"] else 2
        if article_counts.get(article_id, 0) >= article_limit:
            continue
        article_counts[article_id] = article_counts.get(article_id, 0) + 1
        item["rrf_score"] = round(item["rrf_score"], 6)
        selected.append(item)
        if len(selected) >= final_k:
            break
    return selected


def retrieve(
    query: str,
    primary_route: str | None = None,
    patient_data: dict | None = None,
    purpose: str = "general",
    final_k: int = 6,
    n_results: int | None = None,
) -> list[dict]:
    """
    動態選擇 collections 並以 RRF 合併。n_results 是舊介面的相容別名。
    """
    if n_results is not None:
        final_k = n_results
    final_k = max(1, min(int(final_k), 20))
    purpose = purpose if purpose in PURPOSE_QUERY_TERMS else "general"
    query_expansion = _expand_query_terms(query, patient_data)
    original_query = " ".join(
        part
        for part in (
            query_expansion,
            query_expansion,
            query,
            ROUTE_QUERY_TERMS.get(primary_route or "", ""),
            PURPOSE_QUERY_TERMS[purpose],
        )
        if part
    )

    try:
        translation_started = time.perf_counter()
        normalizer = None
        normalized_query = None
        try:
            normalizer = get_query_normalizer()
            normalized_query = normalizer.normalize(query)
        except Exception as exc:
            LOGGER.warning(
                "RAG query translation unavailable error_type=%s",
                type(exc).__name__,
            )
        translation_ms = round(
            (time.perf_counter() - translation_started) * 1000,
            1,
        )
        search_queries = [original_query]
        query_variants = ["original"]
        if normalized_query is not None:
            english_query = " ".join(
                part
                for part in (
                    query_expansion,
                    query_expansion,
                    normalized_query.english_search_text(),
                    ROUTE_QUERY_TERMS.get(primary_route or "", ""),
                    PURPOSE_QUERY_TERMS[purpose],
                )
                if part
            )
            if english_query and english_query != original_query:
                if normalizer and normalizer.query_mode == "english":
                    search_queries = [english_query]
                    query_variants = ["english"]
                else:
                    search_queries.append(english_query)
                    query_variants.append("english")

        if RAG_INDEX_VERSION == "legacy":
            legacy_sets = []
            for variant, search_query in zip(
                query_variants, search_queries
            ):
                results = _legacy_retrieve(search_query, final_k)
                for item in results:
                    item["query_variant"] = variant
                legacy_sets.append(results)
            if len(legacy_sets) == 1:
                return legacy_sets[0]
            return _rrf_merge(legacy_sets, final_k)

        query_embeddings = _registry.embedding_function(
            input=search_queries
        )
        routing_index = (
            query_variants.index("english")
            if "english" in query_variants
            else 0
        )
        semantic_scores = (
            _semantic_route_scores(
                search_queries[routing_index],
                query_embedding=query_embeddings[routing_index],
            )
            if not primary_route
            else None
        )
        routes = select_routes(
            query=query,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose=purpose,
            semantic_scores=semantic_scores,
        )
        result_sets = []
        timings = {}
        for route in routes:
            try:
                if len(search_queries) == 1:
                    results, elapsed = _query_collection(
                        route,
                        search_queries[0],
                        PER_COLLECTION_K,
                        query_embedding=query_embeddings[0],
                    )
                    for item in results:
                        item["query_variant"] = query_variants[0]
                    result_sets.append(results)
                else:
                    variant_results, elapsed = (
                        _query_collection_variants(
                            route,
                            query_embeddings,
                            query_variants,
                            PER_COLLECTION_K,
                        )
                    )
                    result_sets.extend(variant_results)
                timings[route] = round(elapsed * 1000, 1)
            except Exception:
                LOGGER.exception(
                    "RAG collection query failed: route=%s", route
                )

        route_weights = {
            route: (
                1.25
                if route == primary_route
                else 1.5
                if route == "safety" and query_expansion
                else 0.75
                if route == "safety"
                else 1.0
            )
            for route in routes
        }
        merged = _rrf_merge(
            result_sets,
            final_k,
            route_weights=route_weights,
        )
        if not merged and "common" not in routes:
            try:
                if len(search_queries) == 1:
                    common_results, elapsed = _query_collection(
                        "common",
                        search_queries[0],
                        PER_COLLECTION_K,
                        query_embedding=query_embeddings[0],
                    )
                    for item in common_results:
                        item["query_variant"] = query_variants[0]
                    common_result_sets = [common_results]
                else:
                    common_result_sets, elapsed = (
                        _query_collection_variants(
                            "common",
                            query_embeddings,
                            query_variants,
                            PER_COLLECTION_K,
                        )
                    )
                timings["common"] = round(elapsed * 1000, 1)
                merged = _rrf_merge(
                    common_result_sets,
                    final_k,
                    route_weights={"common": 1.0},
                )
                routes.append("common")
            except Exception:
                LOGGER.exception("RAG common fallback failed")

        fallback_used = False
        if not merged and get_rag_status()["legacy_available"]:
            legacy_sets = []
            for variant, search_query in zip(
                query_variants, search_queries
            ):
                results = _legacy_retrieve(search_query, final_k)
                for item in results:
                    item["query_variant"] = variant
                legacy_sets.append(results)
            merged = (
                legacy_sets[0]
                if len(legacy_sets) == 1
                else _rrf_merge(legacy_sets, final_k)
            )
            fallback_used = bool(merged)

        LOGGER.info(
            "RAG query complete routes=%s variants=%s results=%d "
            "translation_ms=%s latency_ms=%s legacy_fallback=%s",
            routes,
            query_variants,
            len(merged),
            translation_ms,
            timings,
            fallback_used,
        )
        return merged
    except Exception:
        LOGGER.exception("RAG query failed")
        return []


def _build_chest_query(patient_data: dict) -> str:
    parts = ["chest pain"]
    onset = f"{patient_data.get('onset_num', '')} {patient_data.get('onset_unit', '')}".strip()
    for value in (
        onset,
        patient_data.get("quality", ""),
        patient_data.get("aggravate", ""),
        patient_data.get("associated", ""),
        patient_data.get("cardio", ""),
    ):
        if value and value != "以上皆無":
            parts.append(str(value))
    return " ".join(parts)


def _build_headache_query(patient_data: dict) -> str:
    parts = ["headache"]
    onset = f"{patient_data.get('onset_num', '')} {patient_data.get('onset_unit', '')}".strip()
    for value in (
        onset,
        patient_data.get("start_type", ""),
        patient_data.get("quality", ""),
        patient_data.get("associated", ""),
        patient_data.get("risk_flags", ""),
        patient_data.get("neuro", ""),
    ):
        if value and value != "以上皆無":
            parts.append(str(value))
    return " ".join(parts)


def _build_abdomen_query(patient_data: dict) -> str:
    parts = ["abdominal pain"]
    onset = f"{patient_data.get('onset_num', '')} {patient_data.get('onset_unit', '')}".strip()
    for value in (
        onset,
        patient_data.get("location", ""),
        patient_data.get("quality", ""),
        patient_data.get("associated", ""),
        patient_data.get("abdomen_hx", ""),
    ):
        if value and value != "以上皆無":
            parts.append(str(value))
    return " ".join(parts)


def build_context(patient_data: dict, ctype: str = "chest") -> str:
    if ctype == "headache":
        query = _build_headache_query(patient_data)
    elif ctype == "abdomen":
        query = _build_abdomen_query(patient_data)
    else:
        ctype = "chest"
        query = _build_chest_query(patient_data)

    chunks = retrieve(
        query,
        primary_route=ctype,
        patient_data=patient_data,
        purpose="diagnosis",
        final_k=6,
    )
    if not chunks:
        return ""

    context_parts = []
    title_counts: dict[str, int] = {}
    for chunk in chunks:
        title = chunk["title"]
        if title_counts.get(title, 0) >= 2:
            continue
        title_counts[title] = title_counts.get(title, 0) + 1
        context_parts.append(
            f"[{chunk['source']} — {title}]\n{chunk['text'][:800]}"
        )
    return "\n\n---\n\n".join(context_parts)

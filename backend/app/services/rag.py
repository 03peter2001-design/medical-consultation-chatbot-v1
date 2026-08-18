"""RAG retrieval helpers shared by patient reports and physician chat."""

from __future__ import annotations

import traceback
from typing import Literal

from fastapi import HTTPException

from app import runtime

KnowledgeBase = Literal["A", "B", "C"]
KNOWLEDGE_BASE_PURPOSE = {
    "A": "diagnosis",
    "B": "lab",
    "C": "imaging",
}


def retrieve_context_block(
    query: str,
    n_results: int = 6,
    primary_route: str | None = None,
    patient_data: dict | None = None,
    purpose: str = "general",
    stage_scope: bool = False,
) -> tuple[str, list[dict]]:
    if runtime.retrieve is None:
        raise HTTPException(status_code=503, detail="RAG 向量庫尚未建立")
    try:
        chunks = runtime.retrieve(
            query,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose=purpose,
            stage_scope=stage_scope,
            final_k=n_results,
        )
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="向量庫查詢失敗，請稍後重試",
        ) from error

    title_counts: dict[str, int] = {}
    context_parts = []
    sources = []
    for chunk in chunks:
        title = chunk["title"]
        if title_counts.get(title, 0) >= 2:
            continue
        title_counts[title] = title_counts.get(title, 0) + 1
        context_parts.append(f"[{chunk['source']} — {title}]\n{chunk['text'][:900]}")
        sources.append(
            {
                "title": title,
                "source": chunk["source"],
                "url": chunk.get("url", ""),
                "route": chunk.get("route", ""),
                "clinical_stage": chunk.get("clinical_stage", "general"),
            }
        )

    context = "\n\n---\n\n".join(context_parts) if context_parts else "（知識庫中查無相關內容）"
    return context, sources


def retrieve_knowledge_base_block(
    knowledge_base: KnowledgeBase,
    query: str,
    *,
    n_results: int,
    primary_route: str | None,
    patient_data: dict | None,
) -> tuple[str, list[dict]]:
    """Retrieve from A, B, or C with v2 stage filters and legacy compatibility."""

    partitioned = runtime.RAG_STATUS.get("index_version") != "legacy"
    context, sources = retrieve_context_block(
        query,
        n_results=n_results,
        primary_route=primary_route,
        patient_data=patient_data,
        purpose=KNOWLEDGE_BASE_PURPOSE[knowledge_base],
        stage_scope=partitioned,
    )
    partition_mode = "clinical_stage" if partitioned else "legacy_unpartitioned"
    return context, [
        {
            **source,
            "knowledge_base": knowledge_base,
            "partition_mode": partition_mode,
        }
        for source in sources
    ]


def deduplicate_sources(
    *source_lists: list[dict],
) -> list[dict]:
    seen = set()
    merged = []
    for sources in source_lists:
        for source in sources:
            if source["title"] not in seen:
                seen.add(source["title"])
                merged.append(source)
    return merged

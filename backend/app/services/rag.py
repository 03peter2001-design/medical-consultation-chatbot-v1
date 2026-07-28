"""RAG retrieval helpers shared by patient reports and physician chat."""

from __future__ import annotations

import traceback

from fastapi import HTTPException

from app import runtime


def retrieve_context_block(
    query: str,
    n_results: int = 6,
    primary_route: str | None = None,
    patient_data: dict | None = None,
    purpose: str = "general",
) -> tuple[str, list[dict]]:
    if runtime.retrieve is None:
        raise HTTPException(status_code=503, detail="RAG 向量庫尚未建立")
    try:
        chunks = runtime.retrieve(
            query,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose=purpose,
            final_k=n_results,
        )
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"向量庫查詢失敗：{error}",
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
            }
        )

    context = "\n\n---\n\n".join(context_parts) if context_parts else "（知識庫中查無相關內容）"
    return context, sources


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

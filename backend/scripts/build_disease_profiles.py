"""One-time RAG-assisted builder for a frozen route disease-profile artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from amie.clinical_facts import FACT_CODES
from amie.disease_profiles import PROFILE_DATA_DIR, validate_profile_document
from amie.rule_config import disease_profile_rules, load_safety_rules
from app import runtime


def _parse_json(text: str) -> Any:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _source_id(chunk: dict[str, Any]) -> str:
    identity = str(chunk.get("url") or chunk.get("title") or chunk.get("chunk_id"))
    return f"rag-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"


def build_document(route: str = "chest") -> dict[str, Any]:
    """Retrieve once, extract constrained profiles, and return a validated artifact."""
    if runtime.retrieve is None:
        raise RuntimeError("RAG 向量庫尚未建立")
    route_rules = disease_profile_rules(route)
    chunks = runtime.retrieve(
        route_rules["generation_query"],
        primary_route=route,
        purpose="diagnosis",
        final_k=20,
    )
    if not chunks:
        raise RuntimeError(f"RAG 未找到可用 {route} 資料")

    sources_by_id: dict[str, dict[str, str]] = {}
    context_parts = []
    for chunk in chunks:
        source_id = _source_id(chunk)
        sources_by_id[source_id] = {
            "id": source_id,
            "title": str(chunk.get("title") or "未命名文章")[:300],
            "source": str(chunk.get("source") or "local-rag")[:120],
            "url": str(chunk.get("url") or "")[:500],
        }
        context_parts.append(f"[source_id={source_id}]\n{str(chunk.get('text') or '')[:1200]}")

    rules = load_safety_rules()
    mandatory = route_rules["required_must_not_miss_profiles"]
    safety_conditions = {
        condition
        for conditions in rules["urgent_condition_candidates"].values()
        for condition in conditions
    }
    mandatory_condition_names = {
        condition for conditions in mandatory.values() for condition in conditions
    }
    if not mandatory_condition_names.issubset(safety_conditions):
        raise ValueError(f"Safety 規則與必要 {route} 疾病清單不同步")
    prompt = f"""
你是離線醫療知識表抽取器。這不是病人診斷，也不會在執行期呼叫。
根據提供的固定文獻片段建立 {route} 鑑別 profile 草稿。

允許的 fact code：
{json.dumps(sorted(FACT_CODES), ensure_ascii=False)}

必須使用指定 id、標記 must_not_miss=true 並納入的 Safety 疾病方向：
{json.dumps(mandatory, ensure_ascii=False)}

規則：
1. 不得發明 fact code；每條 clue 只能引用提供的 source_id。
2. direction 只能是 support 或 oppose，status 只能是 present 或 absent。
3. 不輸出數字權重；程式會統一設為一票。
4. coding 一律輸出 null，避免未驗證術語。
5. 所有 profile 標記 provisional。

文獻：
{"\n\n---\n\n".join(context_parts)}

只回傳：
{{
  "profiles": [
    {{
      "id": "stable_english_slug",
      "name": "繁體中文疾病方向",
      "coding": null,
      "must_not_miss": true,
      "clues": [
        {{
          "fact": "允許的fact code",
          "status": "present",
          "direction": "support",
          "source_ids": ["rag-..."]
        }}
      ]
    }}
  ]
}}
""".strip()
    response = runtime.llm_client.generate_text(
        [
            {
                "role": "system",
                "content": "只做文獻資料結構化抽取，不處理病人、不產生診斷。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=5000,
    )
    payload = _parse_json(response)
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, list):
        raise ValueError("離線模型未回傳 profiles")
    normalized_profiles = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        clues = []
        for clue in profile.get("clues", []):
            if not isinstance(clue, dict):
                continue
            clues.append({**clue, "weight": 1})
        normalized_profiles.append(
            {
                **profile,
                "coding": None,
                "review_status": "provisional",
                "reviewer": None,
                "reviewed_at": None,
                "clues": clues,
            }
        )
    generated_ids = {
        profile.get("id") for profile in normalized_profiles if isinstance(profile, dict)
    }
    mandatory_ids = set(mandatory)
    if not mandatory_ids.issubset(generated_ids):
        missing = sorted(mandatory_ids - generated_ids)
        raise ValueError(f"離線模型缺少 Safety 必要疾病：{missing}")

    corpus_hash = hashlib.sha256(
        "\n".join(
            json.dumps(
                {
                    "chunk_id": chunk.get("chunk_id"),
                    "url": chunk.get("url"),
                    "text": chunk.get("text"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for chunk in chunks
        ).encode()
    ).hexdigest()
    now = datetime.now(timezone.utc)
    document = {
        "schema_version": 1,
        "profile_version": f"{route}-rag-freeze-{now.date().isoformat()}",
        "route": route,
        "generation": {
            "method": "one-time-rag-assisted-profile-extraction",
            "model": runtime.llm_client.model,
            "corpus_hash": corpus_hash,
            "generated_at": now.isoformat(timespec="seconds"),
        },
        "sources": list(sources_by_id.values()),
        "profiles": normalized_profiles,
    }
    return validate_profile_document(document)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--route",
        choices=sorted(load_safety_rules()["disease_profile_rules"]),
        default="chest",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = (args.output or PROFILE_DATA_DIR / f"{args.route}.json").resolve()
    if output.exists() and not args.force:
        raise SystemExit(f"{output} 已存在；一次性重建需明確加上 --force")
    document = build_document(args.route)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已寫入 {len(document['profiles'])} 個 frozen profiles：{output}")


if __name__ == "__main__":
    main()

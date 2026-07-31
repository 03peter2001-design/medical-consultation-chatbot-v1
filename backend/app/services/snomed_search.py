"""Read-only SNOMED text search and HAPI-backed concept lookup."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SNOMED_SYSTEM = "http://snomed.info/sct"
DEFAULT_FHIR_BASE_URL = "http://127.0.0.1:8080/fhir"
DEFAULT_SEARCH_DB = (
    Path(__file__).resolve().parents[2] / "terminology" / "snomed" / "snomed-search.sqlite3"
)


def _operation_outcome_message(payload: dict[str, Any]) -> str:
    messages = [
        str(issue.get("diagnostics") or issue.get("details", {}).get("text") or "").strip()
        for issue in payload.get("issue", [])
        if isinstance(issue, dict)
    ]
    return "；".join(message for message in messages if message)


def _request_json(
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    base_url = os.getenv("FHIR_BASE_URL", DEFAULT_FHIR_BASE_URL).rstrip("/")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url}/{path.lstrip('/')}",
        data=data,
        method=method,
        headers={
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1000]
        if error.code == 404:
            raise LookupError(details) from error
        raise RuntimeError(f"HAPI FHIR 回傳 HTTP {error.code}：{details}") from error
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"無法連接 HAPI FHIR：{error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("HAPI FHIR 回傳格式不正確")
    if payload.get("resourceType") == "OperationOutcome":
        message = _operation_outcome_message(payload) or "SNOMED CT 查詢失敗"
        raise RuntimeError(message)
    return payload


def _lookup_code(code: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"system": SNOMED_SYSTEM, "code": code})
    try:
        payload = _request_json(f"CodeSystem/$lookup?{query}")
    except LookupError:
        return {"query": code, "mode": "code", "total": 0, "items": []}
    parameters = {
        str(item.get("name")): item
        for item in payload.get("parameter", [])
        if isinstance(item, dict)
    }
    display = str(parameters.get("display", {}).get("valueString") or "").strip()
    if not display:
        return {"query": code, "mode": "code", "total": 0, "items": []}
    return {
        "query": code,
        "mode": "code",
        "total": 1,
        "items": [
            {
                "system": SNOMED_SYSTEM,
                "code": code,
                "display": display,
            }
        ],
    }


def _fts_query(query: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z]+", query)
    if not tokens:
        raise ValueError("文字搜尋目前只支援英文術語")
    return " AND ".join(f'"{token}"*' for token in tokens)


def _search_database_path() -> Path:
    configured = os.getenv("SNOMED_SEARCH_DB", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_SEARCH_DB


def _expand_text(query: str, *, limit: int, offset: int) -> dict[str, Any]:
    database_path = _search_database_path()
    if not database_path.is_file():
        raise RuntimeError(
            "找不到本機 SNOMED CT 搜尋索引；請執行 "
            "`python -m scripts.build_snomed_search_index <RF2-ZIP>`"
        )
    match = _fts_query(query)
    connection = sqlite3.connect(
        f"file:{database_path}?mode=ro",
        uri=True,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    try:
        total = int(
            connection.execute(
                "SELECT count(DISTINCT code) FROM terms WHERE terms MATCH ?",
                (match,),
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            WITH matched AS (
                SELECT DISTINCT code
                FROM terms
                WHERE terms MATCH ?
            )
            SELECT concepts.code, concepts.display
            FROM matched
            JOIN concepts ON concepts.code = matched.code
            ORDER BY
                CASE
                    WHEN lower(concepts.display) = lower(?) THEN 0
                    WHEN lower(concepts.display) LIKE lower(?) || '%' THEN 1
                    ELSE 2
                END,
                length(concepts.display),
                concepts.display,
                concepts.code
            LIMIT ? OFFSET ?
            """,
            (match, query, query, limit, offset),
        ).fetchall()
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    except sqlite3.Error as error:
        raise RuntimeError(f"SNOMED CT 搜尋索引無法讀取：{error}") from error
    finally:
        connection.close()

    items = [
        {
            "system": SNOMED_SYSTEM,
            "code": row["code"],
            "display": row["display"],
        }
        for row in rows
    ]
    return {
        "query": query,
        "mode": "text",
        "source": "local-rf2-index",
        "release_date": metadata.get("release_date", ""),
        "total": total,
        "items": items,
    }


def search_snomed(
    raw_query: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    query = str(raw_query or "").strip()
    if len(query) < 2:
        raise ValueError("請輸入至少 2 個字元")
    if len(query) > 120:
        raise ValueError("查詢文字不可超過 120 個字元")
    if not 1 <= limit <= 50 or offset < 0:
        raise ValueError("查詢範圍不正確")

    result = (
        _lookup_code(query) if query.isdigit() else _expand_text(query, limit=limit, offset=offset)
    )
    result["limit"] = limit
    result["offset"] = offset
    result["has_more"] = offset + len(result["items"]) < result["total"]
    return result

#!/usr/bin/env python3
"""Promote clinically signed-off questionnaire drafts into runtime data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
DRAFT_DIR = BACKEND_DIR / "questionnaire_drafts" / "v1"
LIVE_DIR = BACKEND_DIR / "questionnaire_data"
DEFAULT_SIGNOFF_PATH = DRAFT_DIR / "clinical_signoff.json"
ROUTE_CATALOG_PATH = BACKEND_DIR / "domain" / "questionnaire_routes.json"
OVERLAPS = {1: "chest", 2: "headache", 51: "abdomen"}
BLOCKING_REVIEW_SEVERITIES = {"critical", "warning"}
ALLOWED_REVIEW_RESOLUTIONS = {"mitigated", "not_applicable", "accepted_as_safe"}


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} 必須是非空字串")
    return value.strip()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"找不到必要檔案：{path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON 格式錯誤：{path}:{exc.lineno}:{exc.colno}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path} 的根節點必須是物件")
    return document


def _load_promotable_drafts(draft_dir: Path) -> dict[str, dict[str, Any]]:
    drafts: dict[str, dict[str, Any]] = {}
    for path in sorted(draft_dir.glob("[0-9][0-9].json")):
        draft = _load_json(path)
        source_order = int(draft["source_order"])
        if source_order in OVERLAPS:
            continue
        route = _nonempty_string(draft.get("id"), f"{path.name}.id")
        if route in drafts:
            raise ValueError(f"草稿 route 重複：{route}")
        if draft.get("review_status") != "provisional":
            raise ValueError(f"{path.name} 必須維持 provisional 才能進入簽核流程")
        drafts[route] = draft
    if len(drafts) != 49:
        raise RuntimeError(f"預期 49 份新問卷草稿，實際為 {len(drafts)}")
    return drafts


def _validate_note_resolutions(
    route: str,
    draft: dict[str, Any],
    route_signoff: dict[str, Any],
) -> list[dict[str, Any]]:
    notes = draft.get("review_notes", [])
    if not isinstance(notes, list):
        raise ValueError(f"{route}.review_notes 必須是陣列")
    resolutions = route_signoff.get("review_notes")
    if not isinstance(resolutions, list):
        raise ValueError(f"signoff.routes.{route}.review_notes 必須是陣列")

    by_index: dict[int, dict[str, str]] = {}
    for position, item in enumerate(resolutions):
        if not isinstance(item, dict) or set(item) != {
            "note_index",
            "resolution",
            "rationale",
        }:
            raise ValueError(f"signoff.routes.{route}.review_notes[{position}] 格式不正確")
        note_index = item["note_index"]
        if not isinstance(note_index, int) or isinstance(note_index, bool):
            raise ValueError(f"signoff.routes.{route}.review_notes.note_index 必須是整數")
        if note_index in by_index or not 0 <= note_index < len(notes):
            raise ValueError(f"signoff.routes.{route} 含重複或未知 review note：{note_index}")
        resolution = _nonempty_string(
            item["resolution"],
            f"signoff.routes.{route}.review_notes[{position}].resolution",
        )
        if resolution not in ALLOWED_REVIEW_RESOLUTIONS:
            raise ValueError(f"signoff.routes.{route} 的 review note resolution 不受支援")
        by_index[note_index] = {
            "resolution": resolution,
            "rationale": _nonempty_string(
                item["rationale"],
                f"signoff.routes.{route}.review_notes[{position}].rationale",
            ),
        }

    unresolved = [
        index
        for index, note in enumerate(notes)
        if isinstance(note, dict)
        and note.get("severity") in BLOCKING_REVIEW_SEVERITIES
        and index not in by_index
    ]
    if unresolved:
        raise ValueError(f"signoff.routes.{route} 尚有未處理 critical/warning notes：{unresolved}")

    return [
        {
            "note_index": index,
            **note,
            **by_index.get(index, {"resolution": "informational", "rationale": ""}),
        }
        for index, note in enumerate(notes)
    ]


def validate_signoff_manifest(
    signoff: dict[str, Any],
    drafts: dict[str, dict[str, Any]],
    draft_manifest: dict[str, Any],
    route_catalog_sha256: str,
) -> dict[str, Any]:
    expected_keys = {
        "schema_version",
        "reviewer",
        "reviewed_on",
        "source_sha256",
        "route_catalog_sha256",
        "routes",
    }
    if set(signoff) != expected_keys or signoff.get("schema_version") != 1:
        raise ValueError("clinical signoff manifest 格式不正確")

    reviewer = signoff["reviewer"]
    if not isinstance(reviewer, dict) or set(reviewer) != {"name", "role"}:
        raise ValueError("signoff.reviewer 必須包含 name 與 role")
    reviewer = {
        "name": _nonempty_string(reviewer["name"], "signoff.reviewer.name"),
        "role": _nonempty_string(reviewer["role"], "signoff.reviewer.role"),
    }
    reviewed_on = _nonempty_string(signoff["reviewed_on"], "signoff.reviewed_on")
    try:
        date.fromisoformat(reviewed_on)
    except ValueError as exc:
        raise ValueError("signoff.reviewed_on 必須是 YYYY-MM-DD") from exc

    source = draft_manifest.get("source")
    expected_source_hash = source.get("sha256") if isinstance(source, dict) else None
    source_hash = _nonempty_string(signoff["source_sha256"], "signoff.source_sha256")
    if not expected_source_hash or source_hash != expected_source_hash:
        raise ValueError("clinical signoff 的來源 SHA-256 與 draft manifest 不符")
    signed_catalog_hash = _nonempty_string(
        signoff["route_catalog_sha256"],
        "signoff.route_catalog_sha256",
    )
    if signed_catalog_hash != route_catalog_sha256:
        raise ValueError("clinical signoff 的 route catalog SHA-256 與目前檔案不符")

    route_signoffs = signoff["routes"]
    if not isinstance(route_signoffs, dict):
        raise ValueError("signoff.routes 必須是物件")
    if set(route_signoffs) != set(drafts):
        missing = sorted(set(drafts) - set(route_signoffs))
        extra = sorted(set(route_signoffs) - set(drafts))
        raise ValueError(f"clinical signoff routes 不完整；missing={missing}, extra={extra}")

    validated_routes: dict[str, Any] = {}
    for route, draft in drafts.items():
        item = route_signoffs[route]
        if not isinstance(item, dict) or set(item) != {
            "approved",
            "source_sha256",
            "review_notes",
        }:
            raise ValueError(f"signoff.routes.{route} 格式不正確")
        if item["approved"] is not True:
            raise ValueError(f"signoff.routes.{route} 未明確核准")
        draft_source_hash = draft.get("generation", {}).get("source_sha256")
        if item["source_sha256"] != draft_source_hash:
            raise ValueError(f"signoff.routes.{route}.source_sha256 與草稿不符")
        validated_routes[route] = {
            "approved": True,
            "source_sha256": draft_source_hash,
            "review_notes": _validate_note_resolutions(route, draft, item),
        }

    return {
        "reviewer": reviewer,
        "reviewed_on": reviewed_on,
        "source_sha256": source_hash,
        "route_catalog_sha256": signed_catalog_hash,
        "routes": validated_routes,
    }


def _live_document(
    draft: dict[str, Any],
    *,
    validated_signoff: dict[str, Any],
    route_signoff: dict[str, Any],
) -> dict[str, Any]:
    questions = [
        {key: value for key, value in raw.items() if key != "source_lines"}
        for raw in draft["questions"]
    ]
    return {
        "id": draft["id"],
        "label": draft["label"],
        "section": "disease",
        "review_status": "clinically_approved",
        "provenance": {
            "source_order": draft["source_order"],
            "source_sha256": draft["generation"]["source_sha256"],
            "pipeline_version": draft["generation"]["pipeline_version"],
            "model": draft["generation"]["model"],
            "clinical_signoff": {
                "reviewer": validated_signoff["reviewer"],
                "reviewed_on": validated_signoff["reviewed_on"],
                "source_sha256": validated_signoff["source_sha256"],
                "route_catalog_sha256": validated_signoff["route_catalog_sha256"],
            },
        },
        "review_audit": {
            "review_notes": route_signoff["review_notes"],
            "rag_sources": draft.get("rag_sources", []),
        },
        "policy": draft["policy"],
        "questions": questions,
    }


def prepare_promotions(
    draft_dir: Path,
    signoff_path: Path,
) -> dict[str, dict[str, Any]]:
    drafts = _load_promotable_drafts(draft_dir)
    draft_manifest = _load_json(draft_dir / "manifest.json")
    signoff = _load_json(signoff_path)
    catalog_hash = hashlib.sha256(ROUTE_CATALOG_PATH.read_bytes()).hexdigest()
    validated = validate_signoff_manifest(
        signoff,
        drafts,
        draft_manifest,
        catalog_hash,
    )
    return {
        route: _live_document(
            draft,
            validated_signoff=validated,
            route_signoff=validated["routes"][route],
        )
        for route, draft in drafts.items()
    }


def _atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signoff", type=Path, default=DEFAULT_SIGNOFF_PATH)
    args = parser.parse_args(argv)

    promotions = prepare_promotions(DRAFT_DIR, args.signoff)
    for route, document in promotions.items():
        target = LIVE_DIR / f"{route}.json"
        _atomic_write_json(target, document)
        print(f"PROMOTED {route}")
    print(f"PROMOTED {len(promotions)} clinically approved questionnaires")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

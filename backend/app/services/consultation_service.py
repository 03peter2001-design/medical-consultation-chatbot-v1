"""Application logic for generated consultation summaries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from infrastructure.consultation_repository import ConsultationRepository

StructuredNoteGenerator = Callable[
    [dict[str, Any]],
    tuple[str | None, list[dict[str, Any]]],
]
ReportGenerator = Callable[[dict[str, Any]], str | None]


def get_or_create_structured_note(
    repository: ConsultationRepository,
    record: dict[str, Any],
    generator: StructuredNoteGenerator,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Return a cached note or generate and persist it during submission."""
    cached_note = record.get("structured_note")
    if cached_note:
        return cached_note, list(record.get("structured_sources") or [])

    note, sources = generator(record)
    if note:
        repository.save_structured_note(
            record["consultation_id"],
            note,
            sources,
        )
    return note, sources


def process_consultation_summaries(
    repository: ConsultationRepository,
    consultation_id: str,
    report_generator: ReportGenerator,
    structured_note_generator: StructuredNoteGenerator,
    *,
    structured_note_expected: bool,
) -> str:
    """Generate both physician summaries after the response was returned."""
    record = repository.get(consultation_id)
    if not record:
        return "missing"

    errors: list[str] = []
    report_created = False
    note_created = bool(record.get("structured_note"))

    try:
        report = report_generator(record)
        if report:
            repository.save_generated_report(consultation_id, report)
            report_created = True
        else:
            errors.append("AI預問診摘要未產生")
    except Exception as error:
        errors.append(f"AI預問診摘要失敗：{type(error).__name__}")

    refreshed = repository.get(consultation_id)
    if refreshed and structured_note_expected:
        try:
            note, _ = get_or_create_structured_note(
                repository,
                refreshed,
                structured_note_generator,
            )
            note_created = bool(note)
            if not note_created:
                errors.append("六段式RAG摘要未產生")
        except Exception as error:
            errors.append(f"六段式RAG摘要失敗：{type(error).__name__}")

    all_expected_ready = report_created and (note_created or not structured_note_expected)
    any_ready = report_created or note_created
    if all_expected_ready:
        status = "summary_ready"
    elif any_ready:
        status = "summary_partial"
    else:
        status = "summary_failed"
    repository.update_workflow_status(
        consultation_id,
        status,
        error="；".join(errors),
    )
    return status

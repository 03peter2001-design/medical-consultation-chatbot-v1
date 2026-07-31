"""Build a local read-only SNOMED CT text-search index from licensed RF2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sqlite3
import zipfile
from pathlib import Path

SNOMED_DIR = Path(__file__).resolve().parents[1] / "terminology" / "snomed"
DEFAULT_OUTPUT = SNOMED_DIR / "snomed-search.sqlite3"
FSN_TYPE = "900000000000003001"
SYNONYM_TYPE = "900000000000013009"
PREFERRED = "900000000000548007"
US_ENGLISH_REFSET = "900000000000509007"
GB_ENGLISH_REFSET = "900000000000508004"
INSERT_BATCH_SIZE = 5000

csv.field_size_limit(10 * 1024 * 1024)


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_date(path: Path) -> str:
    match = re.search(r"(\d{8})T\d{6}Z", path.name)
    if not match:
        raise ValueError(f"無法從 RF2 檔名判斷版本日期：{path.name}")
    return match.group(1)


def _member(
    archive: zipfile.ZipFile,
    pattern: re.Pattern[str],
) -> str:
    matches = [name for name in archive.namelist() if "/Snapshot/" in name and pattern.search(name)]
    if len(matches) != 1:
        raise ValueError(f"RF2 ZIP 應有且僅有一個 {pattern.pattern} Snapshot")
    return matches[0]


def _rows(archive: zipfile.ZipFile, member: str):
    with archive.open(member) as raw:
        with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            yield from csv.DictReader(text, delimiter="\t")


def _active_concepts(
    archive: zipfile.ZipFile,
    member: str,
) -> set[str]:
    return {row["id"] for row in _rows(archive, member) if row.get("active") == "1"}


def _preferred_descriptions(
    archive: zipfile.ZipFile,
    member: str,
) -> dict[str, int]:
    priorities: dict[str, int] = {}
    for row in _rows(archive, member):
        if row.get("active") != "1" or row.get("acceptabilityId") != PREFERRED:
            continue
        refset_id = row.get("refsetId")
        priority = (
            0 if refset_id == US_ENGLISH_REFSET else 1 if refset_id == GB_ENGLISH_REFSET else 2
        )
        description_id = row["referencedComponentId"]
        priorities[description_id] = min(
            priority,
            priorities.get(description_id, priority),
        )
    return priorities


def _initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE concepts (
            code TEXT PRIMARY KEY,
            display TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE VIRTUAL TABLE terms USING fts5(
            code UNINDEXED,
            term,
            tokenize='unicode61 remove_diacritics 2'
        );
        """
    )


def build_index(
    archive_path: Path,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, str | int]:
    archive_path = archive_path.resolve()
    output_path = output_path.resolve()
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path.unlink(missing_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        concept_member = _member(
            archive,
            re.compile(r"/Terminology/sct2_Concept_Snapshot[^/]*\.txt$"),
        )
        description_member = _member(
            archive,
            re.compile(r"/Terminology/sct2_Description_Snapshot-en_[^/]*\.txt$"),
        )
        language_member = _member(
            archive,
            re.compile(r"/Refset/Language/der2_cRefset_LanguageSnapshot-en_[^/]*\.txt$"),
        )
        active_concepts = _active_concepts(archive, concept_member)
        preferred = _preferred_descriptions(archive, language_member)

        connection = sqlite3.connect(temporary_path)
        try:
            _initialize_database(connection)
            displays: dict[str, tuple[int, str]] = {}
            batch: list[tuple[str, str]] = []
            term_count = 0
            for row in _rows(archive, description_member):
                code = row.get("conceptId", "")
                if (
                    row.get("active") != "1"
                    or row.get("languageCode") != "en"
                    or code not in active_concepts
                ):
                    continue
                term = str(row.get("term") or "").strip()
                if not term:
                    continue
                batch.append((code, term))
                term_count += 1
                if len(batch) >= INSERT_BATCH_SIZE:
                    connection.executemany(
                        "INSERT INTO terms(code, term) VALUES (?, ?)",
                        batch,
                    )
                    batch.clear()

                description_id = row.get("id", "")
                type_id = row.get("typeId")
                priority = preferred.get(
                    description_id,
                    10 if type_id == FSN_TYPE else 20,
                )
                current = displays.get(code)
                if current is None or (priority, len(term), term) < (
                    current[0],
                    len(current[1]),
                    current[1],
                ):
                    displays[code] = (priority, term)

            if batch:
                connection.executemany(
                    "INSERT INTO terms(code, term) VALUES (?, ?)",
                    batch,
                )
            connection.executemany(
                "INSERT INTO concepts(code, display) VALUES (?, ?)",
                ((code, displays.get(code, (99, code))[1]) for code in sorted(active_concepts)),
            )
            metadata = {
                "schema_version": "1",
                "release_date": _release_date(archive_path),
                "archive_name": archive_path.name,
                "archive_sha256": _archive_sha256(archive_path),
                "concept_count": str(len(active_concepts)),
                "term_count": str(term_count),
            }
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                metadata.items(),
            )
            connection.commit()
            connection.execute("INSERT INTO terms(terms) VALUES ('optimize')")
            connection.execute("PRAGMA optimize")
            connection.commit()
        except Exception:
            connection.close()
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            connection.close()

    temporary_path.replace(output_path)
    return {
        "release_date": _release_date(archive_path),
        "concept_count": len(active_concepts),
        "term_count": term_count,
        "output": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a local SQLite FTS index from a licensed SNOMED CT RF2 ZIP"
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_index(args.archive, args.output)
    print(
        "Built SNOMED CT search index: "
        f"{result['concept_count']} concepts, {result['term_count']} terms"
    )
    print(f"Release: {result['release_date']}")
    print(f"Output: {result['output']}")


if __name__ == "__main__":
    main()

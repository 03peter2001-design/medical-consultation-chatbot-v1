"""Install a locally licensed SNOMED CT RF2 release into HAPI FHIR."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .build_snomed_search_index import DEFAULT_OUTPUT, build_index

SNOMED_SYSTEM = "http://snomed.info/sct"
VERIFY_CODE = "29857009"
TERMINOLOGY_DIR = Path(__file__).resolve().parents[1] / "terminology" / "snomed"
MARKER_ID = "snomed-ct-rf2"
MARKER_SYSTEM = (
    "https://github.com/03peter2001-design/medical-consultation-chatbot-v1/snomed-rf2-sha256"
)


def _search_index_matches(archive_sha256: str) -> bool:
    if not DEFAULT_OUTPUT.is_file():
        return False
    try:
        connection = sqlite3.connect(
            f"file:{DEFAULT_OUTPUT.resolve()}?mode=ro",
            uri=True,
        )
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    except sqlite3.Error:
        return False
    finally:
        if "connection" in locals():
            connection.close()
    return metadata.get("archive_sha256") == archive_sha256


def _ensure_search_index(
    archive_path: Path,
    release: dict[str, str],
) -> None:
    if _search_index_matches(release["sha256"]):
        print(f"SNOMED search index is current: {DEFAULT_OUTPUT}")
        return
    result = build_index(archive_path, DEFAULT_OUTPUT)
    print(
        "Built SNOMED search index: "
        f"{result['concept_count']} concepts, {result['term_count']} terms"
    )


def find_release(explicit_path: Path | None = None) -> Path:
    if explicit_path is not None:
        return explicit_path.resolve()
    releases = sorted(TERMINOLOGY_DIR.glob("SnomedCT_*RF2*.zip"))
    if not releases:
        raise FileNotFoundError(
            f"No SNOMED CT RF2 ZIP found in {TERMINOLOGY_DIR}. "
            "Download it from SNOMED International and place it there."
        )
    if len(releases) > 1:
        names = ", ".join(path.name for path in releases)
        raise ValueError(f"Multiple RF2 releases found; pass --archive: {names}")
    return releases[0].resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_release(archive_path: Path) -> dict[str, str]:
    if not archive_path.is_file():
        raise FileNotFoundError(f"SNOMED CT archive not found: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        required = {
            "concept": "Snapshot/Terminology/sct2_Concept_Snapshot_",
            "description": "Snapshot/Terminology/sct2_Description_Snapshot-",
            "relationship": "Snapshot/Terminology/sct2_Relationship_Snapshot_",
        }
        missing = [
            label
            for label, fragment in required.items()
            if not any(fragment in name for name in names)
        ]
        if missing:
            raise ValueError(
                f"{archive_path.name} is not a complete RF2 Snapshot; missing: {', '.join(missing)}"
            )
        release_info_names = [
            name for name in names if name.endswith("/release_package_information.json")
        ]
        if len(release_info_names) != 1:
            raise ValueError("RF2 release_package_information.json is missing or ambiguous")
        release_info = json.loads(archive.read(release_info_names[0]))

    effective_time = str(release_info.get("effectiveTime", ""))
    if len(effective_time) != 8 or not effective_time.isdigit():
        raise ValueError("RF2 effectiveTime is missing or invalid")
    return {"effective_time": effective_time, "sha256": _sha256(archive_path)}


def _request_json(
    url: str,
    *,
    data: dict[str, Any] | None = None,
    method: str = "GET",
    timeout: float = 60,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/fhir+json"}
    if data is not None:
        body = json.dumps(data, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/fhir+json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode(errors="replace")
        raise RuntimeError(f"HAPI returned HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot connect to HAPI: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot connect to HAPI: {exc}") from exc


def _wait_for_hapi(server_url: str, wait_timeout: float) -> None:
    deadline = time.monotonic() + wait_timeout
    last_error = "server is not ready"
    while time.monotonic() < deadline:
        try:
            _request_json(
                f"{server_url.rstrip('/')}/metadata?_summary=true",
                timeout=10,
            )
            return
        except RuntimeError as exc:
            last_error = str(exc)
            time.sleep(2)
    raise RuntimeError(f"HAPI did not become ready within {wait_timeout:g} seconds: {last_error}")


def _marker_matches(server_url: str, release: dict[str, str]) -> bool:
    try:
        marker = _request_json(
            f"{server_url.rstrip('/')}/Basic/{MARKER_ID}",
            timeout=30,
        )
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return False
        raise
    return any(
        identifier.get("system") == MARKER_SYSTEM and identifier.get("value") == release["sha256"]
        for identifier in marker.get("identifier", [])
    )


def _write_marker(server_url: str, release: dict[str, str]) -> None:
    marker = {
        "resourceType": "Basic",
        "id": MARKER_ID,
        "identifier": [{"system": MARKER_SYSTEM, "value": release["sha256"]}],
        "code": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/basic-resource-type",
                    "code": "validation",
                }
            ],
            "text": f"SNOMED CT International RF2 {release['effective_time']}",
        },
    }
    _request_json(
        f"{server_url.rstrip('/')}/Basic/{MARKER_ID}",
        data=marker,
        method="PUT",
        timeout=30,
    )


def _remove_duplicate_placeholders(server_url: str) -> None:
    query = urllib.parse.urlencode({"url": SNOMED_SYSTEM, "_count": "20"})
    bundle = _request_json(
        f"{server_url.rstrip('/')}/CodeSystem?{query}",
        timeout=60,
    )
    resources = [
        entry["resource"]
        for entry in bundle.get("entry", [])
        if entry.get("resource", {}).get("resourceType") == "CodeSystem"
    ]
    if len(resources) <= 1:
        return
    if _code_is_valid(server_url):
        raise RuntimeError(
            "Multiple SNOMED CodeSystems exist and terminology is already loaded; "
            "refusing to choose one automatically"
        )
    if any(resource.get("content") != "not-present" for resource in resources):
        raise RuntimeError(
            "Multiple SNOMED CodeSystems exist and at least one contains concepts; "
            "refusing to delete it"
        )

    resources.sort(
        key=lambda resource: (
            "version" in resource,
            int(resource["id"]) if str(resource.get("id", "")).isdigit() else sys.maxsize,
        )
    )
    keep = resources[0]
    for resource in resources[1:]:
        resource_id = resource.get("id")
        request = urllib.request.Request(
            f"{server_url.rstrip('/')}/CodeSystem/{resource_id}",
            headers={
                "Accept": "application/fhir+json",
                "If-Match": f'W/"{resource.get("meta", {}).get("versionId")}"',
            },
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(request, timeout=60):
                pass
        except urllib.error.HTTPError as exc:
            details = exc.read().decode(errors="replace")
            raise RuntimeError(
                f"Cannot remove duplicate CodeSystem/{resource_id}: HTTP {exc.code}: {details}"
            ) from exc
        print(
            f"Removed duplicate not-present SNOMED placeholder CodeSystem/{resource_id}; "
            f"keeping CodeSystem/{keep['id']}",
            flush=True,
        )


def _upload_with_cli(
    server_url: str,
    archive_path: Path,
    cli_jar: Path,
    timeout: float,
) -> None:
    if not cli_jar.is_file():
        raise FileNotFoundError(f"HAPI FHIR CLI JAR not found: {cli_jar}")
    command = [
        "java",
        "-Xmx4g",
        "-jar",
        str(cli_jar),
        "upload-terminology",
        "-d",
        str(archive_path),
        "-v",
        "r4",
        "-t",
        server_url.rstrip("/"),
        "-u",
        SNOMED_SYSTEM,
        "-s",
        "1GB",
    ]
    try:
        subprocess.run(command, check=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"HAPI FHIR CLI exited with status {exc.returncode}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"SNOMED CT upload exceeded the {timeout:g}-second timeout") from exc


def _code_is_valid(server_url: str) -> bool:
    query = urllib.parse.urlencode({"url": SNOMED_SYSTEM, "code": VERIFY_CODE})
    result = _request_json(
        f"{server_url.rstrip('/')}/CodeSystem/$validate-code?{query}",
        timeout=60,
    )
    return any(
        parameter.get("name") == "result" and parameter.get("valueBoolean") is True
        for parameter in result.get("parameter", [])
    )


def _wait_for_code(server_url: str, verify_timeout: float) -> None:
    deadline = time.monotonic() + verify_timeout
    while time.monotonic() < deadline:
        try:
            if _code_is_valid(server_url):
                return
        except RuntimeError:
            pass
        time.sleep(10)
    raise RuntimeError(
        f"HAPI did not validate SNOMED CT code {VERIFY_CODE} within "
        f"{verify_timeout:g} seconds after upload"
    )


def install_snomed(
    server_url: str,
    archive_path: Path,
    cli_jar: Path,
    *,
    timeout: float = 3600,
    wait_timeout: float = 300,
    verify_timeout: float = 1800,
    force: bool = False,
) -> tuple[dict[str, str], bool]:
    release = inspect_release(archive_path)
    _wait_for_hapi(server_url, wait_timeout)
    if not force and _marker_matches(server_url, release) and _code_is_valid(server_url):
        return release, False

    _remove_duplicate_placeholders(server_url)
    _upload_with_cli(server_url, archive_path, cli_jar, timeout)
    _wait_for_code(server_url, verify_timeout)
    _write_marker(server_url, release)
    return release, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install a licensed SNOMED CT International RF2 ZIP into HAPI FHIR"
    )
    parser.add_argument(
        "--server",
        default=os.getenv("FHIR_BASE_URL", "http://127.0.0.1:8080/fhir"),
    )
    parser.add_argument("--archive", type=Path)
    parser.add_argument(
        "--cli-jar",
        type=Path,
        default=Path(os.getenv("HAPI_FHIR_CLI_JAR", "/opt/hapi-fhir-cli/hapi-fhir-cli.jar")),
        help="Path to the HAPI FHIR CLI JAR",
    )
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--wait-timeout", type=float, default=300)
    parser.add_argument("--verify-timeout", type=float, default=1800)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--finalize-only",
        action="store_true",
        help="Wait for an already submitted import, validate it, and write the marker",
    )
    args = parser.parse_args()

    try:
        archive_path = find_release(args.archive)
        release = inspect_release(archive_path)
        if args.verify_only:
            print(
                f"Verified SNOMED CT International RF2 {release['effective_time']} "
                f"({archive_path.name})"
            )
            print(f"SHA-256: {release['sha256']}")
            return 0

        if args.finalize_only:
            _wait_for_hapi(args.server, args.wait_timeout)
            _wait_for_code(args.server, args.verify_timeout)
            _write_marker(args.server, release)
            _ensure_search_index(archive_path, release)
            print(f"Finalized: SNOMED CT International RF2 {release['effective_time']}")
            print(f"Validated {SNOMED_SYSTEM}#{VERIFY_CODE}")
            return 0

        release, installed = install_snomed(
            args.server,
            archive_path,
            args.cli_jar.resolve(),
            timeout=args.timeout,
            wait_timeout=args.wait_timeout,
            verify_timeout=args.verify_timeout,
            force=args.force,
        )
        _ensure_search_index(archive_path, release)
    except (
        FileNotFoundError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"SNOMED CT installation failed: {exc}", file=sys.stderr)
        return 1

    action = "Installed" if installed else "Already installed"
    print(f"{action}: SNOMED CT International RF2 {release['effective_time']}")
    print(f"HAPI FHIR: {args.server.rstrip('/')}")
    print(f"Validated {SNOMED_SYSTEM}#{VERIFY_CODE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

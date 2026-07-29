"""Install the vendored TW Core FHIR package set into a HAPI FHIR server."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TERMINOLOGY_DIR = Path(__file__).resolve().parents[1] / "terminology"
LOCK_FILE = TERMINOLOGY_DIR / "packages.lock.json"


def _read_lock() -> dict[str, Any]:
    with LOCK_FILE.open(encoding="utf-8") as source:
        return json.load(source)


def _package_manifest(package_path: Path) -> dict[str, Any]:
    with tarfile.open(package_path, "r:gz") as archive:
        manifest = archive.extractfile("package/package.json")
        if manifest is None:
            raise ValueError(f"{package_path}: package/package.json is missing")
        return json.load(manifest)


def _validate_package(spec: dict[str, str]) -> Path:
    package_path = TERMINOLOGY_DIR / spec["file"]
    if not package_path.is_file():
        raise FileNotFoundError(f"FHIR package not found: {package_path}")

    actual_hash = hashlib.sha256(package_path.read_bytes()).hexdigest()
    if actual_hash != spec["sha256"]:
        raise ValueError(
            f"{package_path.name}: SHA-256 mismatch "
            f"(expected {spec['sha256']}, found {actual_hash})"
        )

    manifest = _package_manifest(package_path)
    actual = f"{manifest.get('name')}#{manifest.get('version')}"
    expected = f"{spec['name']}#{spec['version']}"
    if actual != expected:
        raise ValueError(f"{package_path.name}: expected {expected}, found {actual}")
    return package_path


def _install_package(
    server_url: str,
    package_path: Path,
    timeout: float,
) -> dict[str, Any]:
    payload = {
        "resourceType": "Parameters",
        "parameter": [
            {
                "name": "npmContent",
                "valueBase64Binary": base64.b64encode(package_path.read_bytes()).decode(
                    "ascii"
                ),
            }
        ],
    }
    request = urllib.request.Request(
        f"{server_url.rstrip('/')}/ImplementationGuide/$install",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"{package_path.name}: HAPI returned HTTP {exc.code}: {details}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot connect to HAPI at {server_url}: {exc.reason}") from exc


def _wait_for_hapi(server_url: str, wait_timeout: float) -> None:
    metadata_url = f"{server_url.rstrip('/')}/metadata?_summary=true"
    deadline = time.monotonic() + wait_timeout
    last_error = "server is not ready"
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                metadata_url,
                headers={"Accept": "application/fhir+json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(
        f"HAPI at {server_url} did not become ready within "
        f"{wait_timeout:g} seconds: {last_error}"
    )


def install_twcore_packages(
    server_url: str,
    timeout: float = 600,
    *,
    verify_only: bool = False,
    wait_timeout: float = 300,
) -> list[str]:
    """Verify and install the locked package set in dependency order."""
    locked_packages = [
        (spec, _validate_package(spec)) for spec in _read_lock()["packages"]
    ]
    if not verify_only:
        _wait_for_hapi(server_url, wait_timeout)

    installed: list[str] = []
    for spec, package_path in locked_packages:
        package_id = f"{spec['name']}#{spec['version']}"
        if not verify_only:
            print(f"Installing {package_id} ...", flush=True)
            _install_package(server_url, package_path, timeout)
        installed.append(package_id)
    return installed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the vendored TW Core 1.0.0 package set into HAPI FHIR"
    )
    parser.add_argument(
        "--server",
        default=os.getenv("FHIR_BASE_URL", "http://127.0.0.1:8080/fhir"),
        help="HAPI FHIR base URL (default: %(default)s)",
    )
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=300,
        help="Seconds to wait for HAPI startup (default: %(default)s)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Check manifests and SHA-256 hashes without contacting HAPI",
    )
    args = parser.parse_args()

    try:
        packages = install_twcore_packages(
            args.server,
            args.timeout,
            verify_only=args.verify_only,
            wait_timeout=args.wait_timeout,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"TW Core installation failed: {exc}", file=sys.stderr)
        return 1

    action = "Verified" if args.verify_only else "Installed"
    print(f"{action} {len(packages)} locked FHIR packages:")
    for package in packages:
        print(f"- {package}")
    if not args.verify_only:
        print(f"HAPI FHIR: {args.server.rstrip('/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

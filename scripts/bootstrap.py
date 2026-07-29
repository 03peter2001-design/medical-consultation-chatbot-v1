#!/usr/bin/env python3
"""Incrementally prepare the full local development environment."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
STATE_DIR = ROOT / ".build-state"
COMPOSE_FILE = ROOT / "compose.fhir.yml"


class BootstrapError(RuntimeError):
    """Raised when an environment preparation step cannot finish."""


def _log(status: str, message: str) -> None:
    print(f"[{status}] {message}", flush=True)


def _run(
    command: list[str | Path],
    *,
    cwd: Path = ROOT,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    rendered = [str(part) for part in command]
    _log("RUN", " ".join(rendered))
    try:
        return subprocess.run(
            rendered,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=capture,
        )
    except FileNotFoundError as exc:
        raise BootstrapError(f"Command not found: {rendered[0]}") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        suffix = f": {details}" if details else ""
        raise BootstrapError(
            f"Command failed ({exc.returncode}): {' '.join(rendered)}{suffix}"
        ) from exc


def _files_under(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    return sorted(set(files))


def _digest(paths: Iterable[Path], extra: str = "") -> str:
    digest = hashlib.sha256()
    digest.update(extra.encode())
    for path in _files_under(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _stamp_matches(name: str, expected: str) -> bool:
    stamp = STATE_DIR / name
    return stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == expected


def _write_stamp(name: str, value: str) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / name).write_text(f"{value}\n", encoding="utf-8")


def _copy_env_example(directory: Path) -> None:
    target = directory / ".env"
    source = directory / ".env.example"
    if target.exists() or not source.exists():
        _log("SKIP", f"{target.relative_to(ROOT)} already exists")
        return
    shutil.copy2(source, target)
    _log(
        "CREATE", f"{target.relative_to(ROOT)} from .env.example; review local settings"
    )


def _venv_python() -> Path:
    if os.name == "nt":
        return BACKEND_DIR / "venv" / "Scripts" / "python.exe"
    return BACKEND_DIR / "venv" / "bin" / "python"


def _ensure_backend(force: bool) -> Path:
    venv_python = _venv_python()
    if not venv_python.exists():
        _run([sys.executable, "-m", "venv", BACKEND_DIR / "venv"])
    else:
        _log("SKIP", "backend virtual environment already exists")

    requirements = BACKEND_DIR / "requirements.txt"
    dependency_hash = _digest(
        [requirements],
        extra=f"python={sys.version_info.major}.{sys.version_info.minor}\n",
    )
    pip_is_healthy = (
        subprocess.run(
            [venv_python, "-m", "pip", "check"],
            cwd=BACKEND_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )
    if (
        force
        or not pip_is_healthy
        or not _stamp_matches("backend-requirements.sha256", dependency_hash)
    ):
        _run([venv_python, "-m", "pip", "install", "-r", requirements], cwd=BACKEND_DIR)
        _write_stamp("backend-requirements.sha256", dependency_hash)
    else:
        _log("SKIP", "backend requirements are unchanged and pip check passed")

    _copy_env_example(BACKEND_DIR)
    return venv_python


def _node_major() -> int:
    if shutil.which("node") is None or shutil.which("npm") is None:
        raise BootstrapError("Node.js 18+ and npm are required for the frontend")
    version = _run(["node", "--version"], capture=True).stdout.strip().lstrip("v")
    try:
        major = int(version.split(".", 1)[0])
    except ValueError as exc:
        raise BootstrapError(f"Cannot parse Node.js version: {version}") from exc
    if major < 18:
        raise BootstrapError(f"Node.js 18+ is required; found {version}")
    return major


def _ensure_frontend(force: bool) -> None:
    node_major = _node_major()
    dependency_hash = _digest(
        [FRONTEND_DIR / "package.json", FRONTEND_DIR / "package-lock.json"],
        extra=f"node-major={node_major}\n",
    )
    if (
        force
        or not (FRONTEND_DIR / "node_modules").is_dir()
        or not _stamp_matches("frontend-dependencies.sha256", dependency_hash)
    ):
        _run(["npm", "ci"], cwd=FRONTEND_DIR)
        _write_stamp("frontend-dependencies.sha256", dependency_hash)
    else:
        _log("SKIP", "frontend dependencies are unchanged")

    _copy_env_example(FRONTEND_DIR)
    build_inputs = [
        FRONTEND_DIR / "src",
        FRONTEND_DIR / "index.html",
        FRONTEND_DIR / "package.json",
        FRONTEND_DIR / "package-lock.json",
        FRONTEND_DIR / "vite.config.js",
        FRONTEND_DIR / ".env",
    ]
    build_hash = _digest(build_inputs)
    if (
        force
        or not (FRONTEND_DIR / "dist" / "index.html").is_file()
        or not _stamp_matches("frontend-build.sha256", build_hash)
    ):
        _run(["npm", "run", "build"], cwd=FRONTEND_DIR)
        _write_stamp("frontend-build.sha256", build_hash)
    else:
        _log("SKIP", "frontend source and build output are unchanged")


def _ensure_rag(venv_python: Path, force: bool) -> None:
    inputs = [
        BACKEND_DIR / "docs",
        BACKEND_DIR / "scripts" / "clean_documents.py",
        BACKEND_DIR / "scripts" / "classify_chunks.py",
        BACKEND_DIR / "scripts" / "ingest.py",
        BACKEND_DIR / "knowledge",
    ]
    rag_hash = _digest(inputs)
    outputs_exist = all(
        (BACKEND_DIR / path).is_dir()
        for path in ("clean_docs", "classified_docs", "chroma_db")
    )
    if not force and outputs_exist and _stamp_matches("rag-v2.sha256", rag_hash):
        _log("SKIP", "RAG v2 inputs and generated index are unchanged")
        return

    _run([venv_python, "-m", "scripts.clean_documents"], cwd=BACKEND_DIR)
    _run([venv_python, "-m", "scripts.classify_chunks"], cwd=BACKEND_DIR)
    _run(
        [venv_python, "-m", "scripts.ingest", "--version", "v2", "--dry-run"],
        cwd=BACKEND_DIR,
    )
    _run([venv_python, "-m", "scripts.ingest", "--version", "v2"], cwd=BACKEND_DIR)
    _write_stamp("rag-v2.sha256", rag_hash)


def _fhir_is_reachable(base_url: str) -> bool:
    try:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/metadata?_summary=true",
            headers={"Accept": "application/fhir+json"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.HTTPError, urllib.error.URLError):
        return False


def _compose_command(*arguments: str) -> list[str | Path]:
    return ["docker", "compose", "-f", COMPOSE_FILE, *arguments]


def _compose_hapi_is_running() -> bool:
    result = _run(_compose_command("ps", "-q", "hapi"), capture=True)
    container_id = result.stdout.strip()
    if not container_id:
        return False
    state = _run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
        capture=True,
    )
    return state.stdout.strip() == "true"


def _ensure_fhir(venv_python: Path, force: bool) -> None:
    if shutil.which("docker") is None:
        raise BootstrapError("Docker with the Compose plugin is required for HAPI FHIR")
    _run(["docker", "compose", "version"], capture=True)

    explicit_base_url = os.getenv("FHIR_BASE_URL")
    port = os.getenv("FHIR_PORT", "8080")
    local_base_url = explicit_base_url or f"http://127.0.0.1:{port}/fhir"
    compose_running = _compose_hapi_is_running()

    if explicit_base_url:
        _log(
            "SKIP",
            f"Compose HAPI selection overridden by FHIR_BASE_URL={explicit_base_url}",
        )
        use_external_hapi = True
    elif compose_running:
        _log("SKIP", "repository HAPI container is already running")
        use_external_hapi = False
    elif _fhir_is_reachable(local_base_url):
        _log("SKIP", f"another HAPI server is already reachable at {local_base_url}")
        use_external_hapi = True
    else:
        _run(_compose_command("up", "-d", "postgres", "hapi"))
        use_external_hapi = False

    if use_external_hapi:
        command: list[str | Path] = [
            venv_python,
            "-m",
            "scripts.install_twcore",
            "--server",
            local_base_url,
        ]
        if force:
            command.append("--force")
        _run(command, cwd=BACKEND_DIR)
        return

    command = _compose_command("--profile", "setup", "run", "--rm", "twcore-installer")
    if force:
        command.extend(
            [
                "python",
                "-m",
                "scripts.install_twcore",
                "--server",
                "http://hapi:8080/fhir",
                "--force",
            ]
        )
    _run(command)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally prepare backend, frontend, HAPI FHIR and TW Core"
    )
    parser.add_argument(
        "--force", action="store_true", help="rebuild all selected steps"
    )
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-fhir", action="store_true")
    parser.add_argument(
        "--with-rag",
        action="store_true",
        help="build RAG v2 even when backend/.env does not enable it",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        STATE_DIR.mkdir(exist_ok=True)
        if args.skip_backend:
            _log("SKIP", "backend setup disabled by --skip-backend")
            existing_venv_python = _venv_python()
            if args.with_rag and not existing_venv_python.exists():
                raise BootstrapError(
                    "RAG setup requires an existing backend virtual environment"
                )
            venv_python = (
                existing_venv_python
                if existing_venv_python.exists()
                else Path(sys.executable)
            )
        else:
            venv_python = _ensure_backend(args.force)

        if args.skip_frontend:
            _log("SKIP", "frontend setup disabled by --skip-frontend")
        else:
            _ensure_frontend(args.force)

        if args.with_rag:
            _ensure_rag(venv_python, args.force)
        else:
            _log("SKIP", "RAG v2 is opt-in; pass --with-rag to build it")

        if args.skip_fhir:
            _log("SKIP", "FHIR setup disabled by --skip-fhir")
        else:
            _ensure_fhir(venv_python, args.force)
    except BootstrapError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    _log("DONE", "local environment is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

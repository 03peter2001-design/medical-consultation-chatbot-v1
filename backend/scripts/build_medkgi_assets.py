"""Build frozen MedKGI graph assets from a user-supplied PrimeKG CSV export.

The script is deliberately offline-by-default: it never fetches PrimeKG and only loads a
language model when ``--embedding-model`` is explicitly supplied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = BACKEND_DIR / "data" / "medkgi"
ASSET_FILENAME = "primekg.json"
MANIFEST_FILENAME = "manifest.json"
EMBEDDING_FILENAME = "pubmedbert_embeddings.npz"
SCHEMA_VERSION = 1

REQUIRED_COLUMNS = (
    "x_index",
    "y_index",
    "x_id",
    "y_id",
    "x_type",
    "y_type",
    "x_name",
    "y_name",
    "relation",
    "display_relation",
)
DISEASE_TYPES = frozenset({"disease"})
SYMPTOM_TYPES = frozenset({"effect/phenotype", "phenotype", "symptom"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_text(row: dict[str, str | None], field: str, row_number: int) -> str:
    value = row.get(field)
    if value is None or not value.strip():
        raise ValueError(f"PrimeKG row {row_number}: {field} must be a non-empty string")
    return value.strip()


def _node_index(row: dict[str, str | None], field: str, row_number: int) -> int:
    value = _required_text(row, field, row_number)
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"PrimeKG row {row_number}: {field} must be an integer") from exc
    if parsed < 0 or str(parsed) != value:
        raise ValueError(
            f"PrimeKG row {row_number}: {field} must be a canonical non-negative integer"
        )
    return parsed


def _normalized_type(value: str) -> str:
    return " ".join(value.casefold().split())


def _node(
    row: dict[str, str | None],
    side: str,
    row_number: int,
    kind: str,
) -> dict[str, Any]:
    return {
        "id": _node_index(row, f"{side}_index", row_number),
        "external_id": _required_text(row, f"{side}_id", row_number),
        "name": _required_text(row, f"{side}_name", row_number),
        "kind": kind,
    }


def _register_node(nodes: dict[int, dict[str, Any]], node: dict[str, Any], row_number: int) -> None:
    existing = nodes.get(node["id"])
    if existing is not None and existing != node:
        raise ValueError(
            f"PrimeKG row {row_number}: node index {node['id']} has conflicting metadata"
        )
    nodes[node["id"]] = node


def load_primekg(csv_path: Path) -> tuple[dict[str, Any], dict[str, int]]:
    """Validate a PrimeKG CSV and retain disease-symptom/disease-disease edges."""
    if not csv_path.is_file():
        raise ValueError(f"PrimeKG CSV does not exist or is not a file: {csv_path}")

    nodes: dict[int, dict[str, Any]] = {}
    edges: dict[tuple[int, int, str], dict[str, Any]] = {}
    input_rows = 0
    retained_rows = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError("PrimeKG CSV is empty or has no header")
        duplicate_columns = sorted(
            {column for column in reader.fieldnames if reader.fieldnames.count(column) > 1}
        )
        if duplicate_columns:
            raise ValueError(f"PrimeKG CSV has duplicate columns: {duplicate_columns}")
        missing = sorted(set(REQUIRED_COLUMNS) - set(reader.fieldnames))
        if missing:
            raise ValueError(f"PrimeKG CSV is missing required columns: {missing}")

        for row_number, row in enumerate(reader, start=2):
            input_rows += 1
            x_type = _normalized_type(_required_text(row, "x_type", row_number))
            y_type = _normalized_type(_required_text(row, "y_type", row_number))
            x_is_disease = x_type in DISEASE_TYPES
            y_is_disease = y_type in DISEASE_TYPES
            x_is_symptom = x_type in SYMPTOM_TYPES
            y_is_symptom = y_type in SYMPTOM_TYPES

            edge_kind: str | None = None
            if x_is_disease and y_is_disease:
                source_side, target_side = "x", "y"
                source_kind = target_kind = "disease"
                edge_kind = "disease_disease"
            elif x_is_disease and y_is_symptom:
                source_side, target_side = "x", "y"
                source_kind, target_kind = "disease", "symptom"
                edge_kind = "disease_symptom"
            elif y_is_disease and x_is_symptom:
                source_side, target_side = "y", "x"
                source_kind, target_kind = "disease", "symptom"
                edge_kind = "disease_symptom"
            else:
                # Validate every expected field even when the edge will not be retained.
                for field in ("x_id", "y_id", "x_name", "y_name", "relation", "display_relation"):
                    _required_text(row, field, row_number)
                _node_index(row, "x_index", row_number)
                _node_index(row, "y_index", row_number)
                continue

            source_node = _node(row, source_side, row_number, source_kind)
            target_node = _node(row, target_side, row_number, target_kind)
            _register_node(nodes, source_node, row_number)
            _register_node(nodes, target_node, row_number)
            relation = _required_text(row, "relation", row_number)
            display_relation = _required_text(row, "display_relation", row_number)
            edge_key = (
                source_node["id"],
                target_node["id"],
                edge_kind,
            )
            candidate_edge = {
                "source": source_node["id"],
                "target": target_node["id"],
                "kind": edge_kind,
                "relation": relation,
                "display_relation": display_relation,
            }
            existing_edge = edges.get(edge_key)
            if existing_edge is None or (relation, display_relation) < (
                existing_edge["relation"],
                existing_edge["display_relation"],
            ):
                edges[edge_key] = candidate_edge
            retained_rows += 1

    if input_rows == 0:
        raise ValueError("PrimeKG CSV contains no data rows")
    if not edges:
        raise ValueError("PrimeKG CSV contains no disease-symptom or disease-disease edges")

    ordered_nodes = [nodes[node_id] for node_id in sorted(nodes)]
    ordered_edges = [edges[key] for key in sorted(edges)]
    counts = {
        "input_rows": input_rows,
        "retained_rows": retained_rows,
        "skipped_rows": input_rows - retained_rows,
        "nodes": len(ordered_nodes),
        "disease_nodes": sum(node["kind"] == "disease" for node in ordered_nodes),
        "symptom_nodes": sum(node["kind"] == "symptom" for node in ordered_nodes),
        "edges": len(ordered_edges),
        "disease_symptom_edges": sum(edge["kind"] == "disease_symptom" for edge in ordered_edges),
        "disease_disease_edges": sum(edge["kind"] == "disease_disease" for edge in ordered_edges),
        "duplicate_edges_removed": retained_rows - len(ordered_edges),
    }
    return {"nodes": ordered_nodes, "edges": ordered_edges}, counts


def _write_embeddings(
    path: Path,
    nodes: list[dict[str, Any]],
    model_argument: str,
    batch_size: int,
) -> dict[str, Any]:
    """Write normalized mean-pooled embeddings, importing optional packages lazily."""
    try:
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "Embedding generation requires the backend NumPy, PyTorch, and Transformers packages"
        ) from exc

    if model_argument.startswith("hf://"):
        model_ref = model_argument.removeprefix("hf://")
        if not model_ref:
            raise ValueError("--embedding-model hf:// must include a Hugging Face repository ID")
        local_only = False
    else:
        model_path = Path(model_argument).expanduser()
        if not model_path.is_dir():
            raise ValueError(
                "--embedding-model must be a local model directory or an explicit hf:// repository ID"
            )
        model_ref = str(model_path.resolve())
        local_only = True

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_ref,
            local_files_only=local_only,
            trust_remote_code=False,
        )
        model = AutoModel.from_pretrained(
            model_ref,
            local_files_only=local_only,
            trust_remote_code=False,
        )
    except Exception as exc:
        location = "local directory" if local_only else "Hugging Face repository"
        raise RuntimeError(
            f"Could not load PubMedBERT from {location} {model_ref!r}: {exc}"
        ) from exc

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()
    matrices = []
    with torch.inference_mode():
        for start in range(0, len(nodes), batch_size):
            texts = [node["name"] for node in nodes[start : start + batch_size]]
            tokens = tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=128,
                return_tensors="pt",
            ).to(device)
            output = model(**tokens).last_hidden_state
            mask = tokens["attention_mask"].unsqueeze(-1).to(output.dtype)
            pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            matrices.append(pooled.cpu().numpy().astype("float32", copy=False))
    embeddings = np.concatenate(matrices, axis=0)
    np.savez_compressed(
        path,
        node_ids=np.asarray([node["id"] for node in nodes], dtype="int64"),
        embeddings=embeddings,
    )
    return {
        "model": model_argument,
        "pooling": "attention-mask-mean",
        "normalized": True,
        "dimensions": int(embeddings.shape[1]),
        "node_count": len(nodes),
        "device_type": device.type,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def build_assets(
    primekg_csv: Path,
    output_dir: Path,
    source_version: str,
    *,
    embedding_model: str | None = None,
    embedding_batch_size: int = 32,
    force: bool = False,
    generated_at: datetime | None = None,
    embedding_writer: Callable[[Path, list[dict[str, Any]], str, int], dict[str, Any]]
    | None = None,
) -> dict[str, Any]:
    """Build and atomically publish MedKGI assets after all validation succeeds."""
    source_version = source_version.strip()
    if not source_version:
        raise ValueError("--source-version must be a non-empty PrimeKG release identifier")
    if embedding_batch_size < 1:
        raise ValueError("--embedding-batch-size must be at least 1")
    output_dir = output_dir.resolve()
    final_paths = [output_dir / ASSET_FILENAME, output_dir / MANIFEST_FILENAME]
    if embedding_model is not None:
        final_paths.append(output_dir / EMBEDDING_FILENAME)
    existing = [path for path in final_paths if path.exists()]
    if existing and not force:
        raise FileExistsError(
            "Output already exists; use --force to replace this build: "
            + ", ".join(str(path) for path in existing)
        )

    graph, counts = load_primekg(primekg_csv.resolve())
    timestamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp_text = timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")
    source_hash = _sha256(primekg_csv)
    asset = {
        "schema_version": SCHEMA_VERSION,
        "source": {"version": source_version, "sha256": source_hash},
        "generated_at": timestamp_text,
        **graph,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    writer = embedding_writer or _write_embeddings
    with tempfile.TemporaryDirectory(prefix=".medkgi-build-", dir=output_dir) as temporary:
        staging = Path(temporary)
        asset_path = staging / ASSET_FILENAME
        _write_json(asset_path, asset)
        artifacts: dict[str, dict[str, Any]] = {
            "primekg": {
                "path": ASSET_FILENAME,
                "sha256": _sha256(asset_path),
                "bytes": asset_path.stat().st_size,
            }
        }
        embedding_metadata = None
        if embedding_model is not None:
            embedding_path = staging / EMBEDDING_FILENAME
            embedding_metadata = writer(
                embedding_path,
                graph["nodes"],
                embedding_model,
                embedding_batch_size,
            )
            if not embedding_path.is_file():
                raise RuntimeError("Embedding writer did not create the requested output file")
            artifacts["embeddings"] = {
                "path": EMBEDDING_FILENAME,
                "sha256": _sha256(embedding_path),
                "bytes": embedding_path.stat().st_size,
                **embedding_metadata,
            }

        manifest = {
            "artifact_kind": "medkgi_primekg_assets",
            "schema_version": SCHEMA_VERSION,
            "generated_at": timestamp_text,
            "source": {
                "path": str(primekg_csv.resolve()),
                "version": source_version,
                "sha256": source_hash,
            },
            "counts": counts,
            "artifacts": artifacts,
        }
        manifest_path = staging / MANIFEST_FILENAME
        _write_json(manifest_path, manifest)

        os.replace(asset_path, output_dir / ASSET_FILENAME)
        if embedding_model is not None:
            os.replace(staging / EMBEDDING_FILENAME, output_dir / EMBEDDING_FILENAME)
        os.replace(manifest_path, output_dir / MANIFEST_FILENAME)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primekg-csv", type=Path, required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--embedding-model",
        help="Local PubMedBERT directory or explicit hf://<repository-id>; omitted by default",
    )
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        manifest = build_assets(
            args.primekg_csv,
            args.output_dir,
            args.source_version,
            embedding_model=args.embedding_model,
            embedding_batch_size=args.embedding_batch_size,
            force=args.force,
        )
    except (FileExistsError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"Wrote {manifest['counts']['nodes']} nodes and {manifest['counts']['edges']} edges "
        f"to {args.output_dir.resolve()}"
    )


if __name__ == "__main__":
    main()

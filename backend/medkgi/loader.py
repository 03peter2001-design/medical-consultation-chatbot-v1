"""Fail-closed loading for locally built PrimeKG MedKGI assets.

Loaded graphs are research evidence, not a formal diagnosis. They remain
unreviewed until explicitly approved through the clinical governance process.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .graph import SCHEMA_VERSION, KnowledgeGraph, MedKGIAssetError, MedKGIUnavailable
from .models import (
    DiseaseNode,
    DiseaseSymptomEdge,
    GraphProvenance,
    SymptomNode,
)


class MedKGILoader:
    """Validate and load the versioned output of build_medkgi_assets.py."""

    @classmethod
    def load(
        cls,
        kg_path: str | Path,
        manifest_path: str | Path,
        embeddings_path: str | Path | None = None,
    ) -> KnowledgeGraph:
        graph_file = Path(kg_path)
        manifest_file = Path(manifest_path)
        try:
            manifest = cls._object(manifest_file, "manifest")
            graph_bytes = graph_file.read_bytes()
            graph = json.loads(graph_bytes)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise MedKGIUnavailable("MedKGI graph or manifest is unavailable or invalid") from error
        if not isinstance(graph, dict):
            raise MedKGIUnavailable("MedKGI graph JSON must be an object")
        if graph.get("schema_version") != SCHEMA_VERSION:
            raise MedKGIUnavailable("unsupported MedKGI graph schema_version")
        cls._validate_header(manifest, graph_file, graph_bytes)

        source = manifest.get("source")
        artifacts = manifest.get("artifacts")
        if not isinstance(source, dict) or not isinstance(artifacts, dict):
            raise MedKGIUnavailable("manifest source and artifacts must be objects")
        version = cls._text(source.get("version"), "source.version")
        source_hash = cls._digest(source.get("sha256"), "source.sha256")
        graph_source = graph.get("source")
        if not isinstance(graph_source, dict):
            raise MedKGIUnavailable("graph source must be an object")
        if graph_source.get("version") != version or graph_source.get("sha256") != source_hash:
            raise MedKGIUnavailable("graph source provenance does not match manifest")

        raw_nodes = graph.get("nodes")
        raw_edges = graph.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise MedKGIUnavailable("graph nodes and edges must be lists")

        diseases: dict[str, DiseaseNode] = {}
        symptoms: dict[str, SymptomNode] = {}
        node_order: list[str] = []
        node_kinds: dict[str, str] = {}
        for index, raw in enumerate(raw_nodes):
            if not isinstance(raw, dict):
                raise MedKGIUnavailable(f"nodes[{index}] must be an object")
            raw_id = raw.get("id")
            if raw_id is None or isinstance(raw_id, bool):
                raise MedKGIUnavailable(f"nodes[{index}].id is invalid")
            entity_id = str(raw_id)
            if entity_id in node_kinds:
                raise MedKGIUnavailable(f"duplicate node id: {entity_id}")
            kind = raw.get("kind")
            name = cls._text(raw.get("name"), f"nodes[{index}].name")
            if kind == "disease":
                diseases[entity_id] = DiseaseNode(entity_id, name)
            elif kind == "symptom":
                symptoms[entity_id] = SymptomNode(entity_id, name)
            else:
                raise MedKGIUnavailable(f"nodes[{index}].kind is unsupported")
            node_order.append(entity_id)
            node_kinds[entity_id] = kind

        evidence_edges: list[DiseaseSymptomEdge] = []
        for index, raw in enumerate(raw_edges):
            if not isinstance(raw, dict):
                raise MedKGIUnavailable(f"edges[{index}] must be an object")
            kind = raw.get("kind")
            if kind == "disease_disease":
                continue
            if kind != "disease_symptom":
                raise MedKGIUnavailable(f"edges[{index}].kind is unsupported")
            source_id, target_id = str(raw.get("source")), str(raw.get("target"))
            if node_kinds.get(source_id) != "disease" or node_kinds.get(target_id) != "symptom":
                raise MedKGIUnavailable(f"edges[{index}] has invalid disease-symptom endpoints")
            evidence_edges.append(DiseaseSymptomEdge(source_id, target_id))

        embeddings = None
        embedding_hash = ""
        embedding_model = ""
        if embeddings_path is not None:
            embeddings, embedding_hash, embedding_model = cls._load_embeddings(
                Path(embeddings_path), artifacts, node_order
            )

        provenance = GraphProvenance(
            schema_version=SCHEMA_VERSION,
            knowledge_graph_version=version,
            created_at=cls._text(manifest.get("generated_at"), "generated_at"),
            source_name="PrimeKG",
            source_uri=cls._text(source.get("path"), "source.path"),
            source_license="unspecified",
            review_status="research_unreviewed",
            reviewer="none",
            review_date="not-reviewed",
            graph_sha256=hashlib.sha256(graph_bytes).hexdigest(),
            embedding_sha256=embedding_hash,
            embedding_model=embedding_model,
        )
        try:
            return KnowledgeGraph(
                provenance,
                diseases,
                symptoms,
                tuple(evidence_edges),
                node_embeddings=embeddings,
            )
        except MedKGIAssetError as error:
            raise MedKGIUnavailable(str(error)) from error

    @classmethod
    def _validate_header(
        cls, manifest: dict[str, Any], graph_path: Path, graph_bytes: bytes
    ) -> None:
        if manifest.get("artifact_kind") != "medkgi_primekg_assets":
            raise MedKGIUnavailable("unsupported MedKGI artifact_kind")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise MedKGIUnavailable("unsupported MedKGI manifest schema_version")
        artifacts = manifest.get("artifacts")
        primekg = artifacts.get("primekg") if isinstance(artifacts, dict) else None
        if not isinstance(primekg, dict):
            raise MedKGIUnavailable("manifest artifacts.primekg must be an object")
        declared = cls._text(primekg.get("path"), "artifacts.primekg.path")
        if Path(declared).name != declared or graph_path.name != declared:
            raise MedKGIUnavailable("PrimeKG graph path does not match manifest")
        expected = cls._digest(primekg.get("sha256"), "artifacts.primekg.sha256")
        if hashlib.sha256(graph_bytes).hexdigest() != expected:
            raise MedKGIUnavailable("PrimeKG graph hash does not match manifest")

    @classmethod
    def _load_embeddings(
        cls,
        path: Path,
        artifacts: dict[str, Any],
        expected_node_ids: list[str],
    ) -> tuple[dict[str, tuple[float, ...]], str, str]:
        artifact = artifacts.get("embeddings")
        if not isinstance(artifact, dict):
            raise MedKGIUnavailable("embeddings path configured but artifact is not declared")
        declared = cls._text(artifact.get("path"), "artifacts.embeddings.path")
        if Path(declared).name != declared or path.name != declared:
            raise MedKGIUnavailable("embedding path does not match manifest")
        expected_hash = cls._digest(artifact.get("sha256"), "artifacts.embeddings.sha256")
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise MedKGIUnavailable("MedKGI embeddings are unavailable") from error
        if hashlib.sha256(payload).hexdigest() != expected_hash:
            raise MedKGIUnavailable("embedding hash does not match manifest")
        try:
            import numpy as np

            with np.load(path, allow_pickle=False) as archive:
                node_ids = [str(value) for value in archive["node_ids"].tolist()]
                matrix = archive["embeddings"]
                if matrix.ndim != 2 or not np.isfinite(matrix).all():
                    raise MedKGIUnavailable("embedding matrix must be finite and two-dimensional")
                vectors = matrix.tolist()
        except MedKGIUnavailable:
            raise
        except (ImportError, OSError, KeyError, ValueError) as error:
            raise MedKGIUnavailable("embedding NPZ is invalid or cannot be loaded") from error
        if node_ids != expected_node_ids:
            raise MedKGIUnavailable("embedding node_ids do not match graph node order")
        if artifact.get("node_count") != len(node_ids):
            raise MedKGIUnavailable("embedding node_count does not match NPZ")
        dimensions = artifact.get("dimensions")
        if not isinstance(dimensions, int) or dimensions < 1:
            raise MedKGIUnavailable("embedding dimensions must be a positive integer")
        if any(len(vector) != dimensions for vector in vectors):
            raise MedKGIUnavailable("embedding dimensions do not match NPZ")
        mapping = {
            entity_id: tuple(float(value) for value in vector)
            for entity_id, vector in zip(node_ids, vectors)
        }
        return (
            mapping,
            expected_hash,
            cls._text(artifact.get("model"), "artifacts.embeddings.model"),
        )

    @staticmethod
    def _object(path: Path, label: str) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise MedKGIUnavailable(f"{label} JSON must be an object")
        return payload

    @staticmethod
    def _text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise MedKGIUnavailable(f"{field} must be non-empty text")
        return value.strip()

    @staticmethod
    def _digest(value: Any, field: str) -> str:
        digest = MedKGILoader._text(value, field).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MedKGIUnavailable(f"{field} must be a SHA-256 digest")
        return digest

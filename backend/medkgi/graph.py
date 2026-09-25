"""Versioned local knowledge-graph loading and entity alignment for MedKGI.

The loader intentionally fails closed on missing, unreviewed, inconsistent, or
tampered production assets. Synthetic in-memory graphs are test-only and are
clearly marked in provenance. This code does not provide a formal diagnosis.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import (
    Alignment,
    DiseaseNode,
    DiseaseSymptomEdge,
    EntityKind,
    GraphProvenance,
    SymptomNode,
)

SCHEMA_VERSION = 1
SEMANTIC_ALIGNMENT_THRESHOLD = 0.85


class MedKGIAssetError(RuntimeError):
    """Raised when local MedKGI assets cannot be trusted or loaded."""


class MedKGIUnavailable(MedKGIAssetError):
    """Raised when production MedKGI assets are missing or fail validation."""


class Embedder(Protocol):
    """Optional local embedding interface; implementations must not require a network."""

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def _normalized(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip()
    normalized = re.sub(r"^[A-Z][A-Z0-9]{1,9}\s*-\s+", "", normalized)
    normalized = " ".join(normalized.casefold().split())
    return re.sub(r"\s+\((?:disease|disorder|finding)\)$", "", normalized).strip()


def _eligible_for_edit_distance(text: str) -> bool:
    return len(text) >= 5 and re.fullmatch(r"[\x20-\x7e]+", text) is not None


def _eligible_for_semantic_alignment(text: str) -> bool:
    return re.fullmatch(r"[\x20-\x7e]+", text) is not None and re.search(r"[a-z]", text) is not None


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MedKGIAssetError(f"{field} must be non-empty text")
    return value.strip()


def _aliases(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MedKGIAssetError(f"{field} must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


@dataclass(frozen=True)
class KnowledgeGraph:
    provenance: GraphProvenance
    diseases: Mapping[str, DiseaseNode]
    symptoms: Mapping[str, SymptomNode]
    edges: tuple[DiseaseSymptomEdge, ...]
    node_embeddings: Mapping[str, tuple[float, ...]] | None = None

    def __post_init__(self) -> None:
        if not self.diseases or not self.symptoms or not self.edges:
            raise MedKGIAssetError("knowledge graph must contain diseases, symptoms, and edges")
        seen_edges: set[tuple[str, str]] = set()
        for edge in self.edges:
            key = (edge.disease_id, edge.symptom_id)
            if edge.disease_id not in self.diseases or edge.symptom_id not in self.symptoms:
                raise MedKGIAssetError(f"edge references an unknown entity: {key}")
            if key in seen_edges:
                raise MedKGIAssetError(f"duplicate disease-symptom edge: {key}")
            if edge.probability is not None and not 0 < edge.probability < 1:
                raise MedKGIAssetError(f"edge probability must be between zero and one: {key}")
            seen_edges.add(key)
        self._validate_labels("disease", self.diseases.values())
        self._validate_labels("symptom", self.symptoms.values())

    @staticmethod
    def _validate_labels(kind: str, nodes: Any) -> None:
        for node in nodes:
            for label in (node.name, *node.aliases):
                normalized = _normalized(label)
                if not normalized:
                    raise MedKGIAssetError(f"{kind} contains an empty normalized label")

    @classmethod
    def load_local(cls, asset_directory: str | Path) -> KnowledgeGraph:
        """Load clinician-reviewed local assets after manifest and hash verification."""

        directory = Path(asset_directory)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise MedKGIAssetError(f"MedKGI manifest is missing: {manifest_path}")
        manifest = cls._read_object(manifest_path, "manifest")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise MedKGIAssetError("unsupported MedKGI manifest schema_version")
        if manifest.get("artifact_kind") == "medkgi_primekg_assets":
            from .loader import MedKGILoader

            artifacts = manifest.get("artifacts")
            primekg = artifacts.get("primekg") if isinstance(artifacts, dict) else None
            if not isinstance(primekg, dict):
                raise MedKGIUnavailable("manifest artifacts.primekg must be an object")
            graph_name = _required_text(primekg.get("path"), "artifacts.primekg.path")
            embedding = artifacts.get("embeddings")
            embedding_path = None
            if isinstance(embedding, dict):
                embedding_name = _required_text(embedding.get("path"), "artifacts.embeddings.path")
                embedding_path = directory / embedding_name
            return MedKGILoader.load(
                directory / graph_name,
                manifest_path,
                embeddings_path=embedding_path,
            )

        graph_file = _required_text(manifest.get("graph_file"), "graph_file")
        if Path(graph_file).name != graph_file:
            raise MedKGIAssetError("graph_file must be a filename within the asset directory")
        expected_hash = _required_text(manifest.get("graph_sha256"), "graph_sha256").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise MedKGIAssetError("graph_sha256 must be a lowercase SHA-256 digest")
        graph_path = directory / graph_file
        if not graph_path.is_file():
            raise MedKGIAssetError(f"MedKGI graph file is missing: {graph_path}")
        graph_bytes = graph_path.read_bytes()
        actual_hash = hashlib.sha256(graph_bytes).hexdigest()
        if actual_hash != expected_hash:
            raise MedKGIAssetError("MedKGI graph hash does not match its manifest")

        source = manifest.get("source")
        review = manifest.get("review")
        if not isinstance(source, dict) or not isinstance(review, dict):
            raise MedKGIAssetError("manifest source and review must be objects")
        if review.get("status") != "clinician_reviewed":
            raise MedKGIAssetError("production MedKGI assets must be clinician_reviewed")
        provenance = GraphProvenance(
            schema_version=SCHEMA_VERSION,
            knowledge_graph_version=_required_text(
                manifest.get("knowledge_graph_version"), "knowledge_graph_version"
            ),
            created_at=_required_text(manifest.get("created_at"), "created_at"),
            source_name=_required_text(source.get("name"), "source.name"),
            source_uri=_required_text(source.get("uri"), "source.uri"),
            source_license=_required_text(source.get("license"), "source.license"),
            review_status="clinician_reviewed",
            reviewer=_required_text(review.get("reviewer"), "review.reviewer"),
            review_date=_required_text(review.get("date"), "review.date"),
            graph_sha256=actual_hash,
        )
        graph_data = json.loads(graph_bytes)
        if not isinstance(graph_data, dict):
            raise MedKGIAssetError("graph JSON must be an object")
        return cls._from_document(graph_data, provenance)

    @classmethod
    def from_records(
        cls,
        *,
        version: str,
        diseases: Sequence[Mapping[str, Any]],
        symptoms: Sequence[Mapping[str, Any]],
        edges: Sequence[Mapping[str, Any]],
    ) -> KnowledgeGraph:
        """Build a conspicuously synthetic graph for deterministic tests."""

        provenance = GraphProvenance(
            schema_version=SCHEMA_VERSION,
            knowledge_graph_version=_required_text(version, "version"),
            created_at="synthetic",
            source_name="synthetic-test-fixture",
            source_uri="local-memory",
            source_license="test-only",
            review_status="synthetic_unreviewed",
            reviewer="none",
            review_date="not-reviewed",
            graph_sha256="in-memory",
        )
        return cls._from_document(
            {
                "schema_version": SCHEMA_VERSION,
                "knowledge_graph_version": version,
                "diseases": list(diseases),
                "symptoms": list(symptoms),
                "edges": list(edges),
            },
            provenance,
        )

    @staticmethod
    def _read_object(path: Path, label: str) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise MedKGIAssetError(f"invalid {label} JSON") from error
        if not isinstance(payload, dict):
            raise MedKGIAssetError(f"{label} JSON must be an object")
        return payload

    @classmethod
    def _from_document(
        cls,
        document: Mapping[str, Any],
        provenance: GraphProvenance,
    ) -> KnowledgeGraph:
        if document.get("schema_version") != SCHEMA_VERSION:
            raise MedKGIAssetError("unsupported graph schema_version")
        if document.get("knowledge_graph_version") != provenance.knowledge_graph_version:
            raise MedKGIAssetError("graph version does not match manifest provenance")
        raw_diseases = document.get("diseases")
        raw_symptoms = document.get("symptoms")
        raw_edges = document.get("edges")
        if not all(isinstance(items, list) for items in (raw_diseases, raw_symptoms, raw_edges)):
            raise MedKGIAssetError("graph diseases, symptoms, and edges must be lists")

        diseases: dict[str, DiseaseNode] = {}
        for index, raw in enumerate(raw_diseases):
            if not isinstance(raw, dict):
                raise MedKGIAssetError(f"diseases[{index}] must be an object")
            entity_id = _required_text(raw.get("id"), f"diseases[{index}].id")
            prior = raw.get("prior")
            if prior is not None and (
                isinstance(prior, bool)
                or not isinstance(prior, (int, float))
                or not math.isfinite(float(prior))
                or float(prior) < 0
            ):
                raise MedKGIAssetError(f"diseases[{index}].prior must be finite and non-negative")
            if entity_id in diseases:
                raise MedKGIAssetError(f"duplicate disease id: {entity_id}")
            diseases[entity_id] = DiseaseNode(
                entity_id=entity_id,
                name=_required_text(raw.get("name"), f"diseases[{index}].name"),
                aliases=_aliases(raw.get("aliases"), f"diseases[{index}].aliases"),
                prior=float(prior) if prior is not None else None,
            )

        symptoms: dict[str, SymptomNode] = {}
        for index, raw in enumerate(raw_symptoms):
            if not isinstance(raw, dict):
                raise MedKGIAssetError(f"symptoms[{index}] must be an object")
            entity_id = _required_text(raw.get("id"), f"symptoms[{index}].id")
            if entity_id in symptoms:
                raise MedKGIAssetError(f"duplicate symptom id: {entity_id}")
            symptoms[entity_id] = SymptomNode(
                entity_id=entity_id,
                name=_required_text(raw.get("name"), f"symptoms[{index}].name"),
                aliases=_aliases(raw.get("aliases"), f"symptoms[{index}].aliases"),
            )

        parsed_edges = []
        for index, raw in enumerate(raw_edges):
            if not isinstance(raw, dict):
                raise MedKGIAssetError(f"edges[{index}] must be an object")
            probability = raw.get("probability")
            parsed_edges.append(
                DiseaseSymptomEdge(
                    disease_id=_required_text(raw.get("disease_id"), f"edges[{index}].disease_id"),
                    symptom_id=_required_text(raw.get("symptom_id"), f"edges[{index}].symptom_id"),
                    probability=float(probability) if probability is not None else None,
                )
            )
        return cls(provenance, diseases, symptoms, tuple(parsed_edges))

    def symptom_edges(self, disease_id: str) -> tuple[DiseaseSymptomEdge, ...]:
        return tuple(edge for edge in self.edges if edge.disease_id == disease_id)

    def disease_ids_for_symptom(self, symptom_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(edge.disease_id for edge in self.edges if edge.symptom_id == symptom_id)
        )

    def edge_probability(self, disease_id: str, symptom_id: str, smoothing: float) -> float:
        edges = self.symptom_edges(disease_id)
        edge = next((item for item in edges if item.symptom_id == symptom_id), None)
        raw_probability = edge.probability if edge and edge.probability is not None else None
        probability = (
            raw_probability if raw_probability is not None else (1 / len(edges) if edge else 0)
        )
        return min(1 - smoothing, max(smoothing, probability))


class EntityAligner:
    """Align terms by exact match, edit distance <= 3, then optional embeddings."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        *,
        embedder: Embedder | None = None,
        semantic_threshold: float = SEMANTIC_ALIGNMENT_THRESHOLD,
    ):
        if not 0 < semantic_threshold <= 1:
            raise ValueError("semantic_threshold must be in (0, 1]")
        self.graph = graph
        self.embedder = embedder
        self.semantic_threshold = semantic_threshold

    def align(self, term: str, kind: EntityKind) -> Alignment | None:
        query = term.strip()
        normalized_query = _normalized(query)
        if not normalized_query:
            return None
        nodes = self.graph.diseases if kind == "disease" else self.graph.symptoms
        labels = sorted(
            (
                (_normalized(label), node.entity_id, node.name)
                for node in nodes.values()
                for label in (node.name, *node.aliases)
            ),
            key=lambda item: (item[0], item[2].casefold(), item[1]),
        )
        exact_matches = [item for item in labels if item[0] == normalized_query]
        exact_ids = {item[1] for item in exact_matches}
        if len(exact_ids) == 1:
            _, entity_id, name = min(exact_matches, key=lambda item: (item[2].casefold(), item[1]))
            return Alignment(query, kind, entity_id, name, "exact", 1.0)
        if len(exact_ids) > 1:
            return None

        eligible = []
        if _eligible_for_edit_distance(normalized_query):
            edit_matches = [
                (
                    self._levenshtein(normalized_query, label, maximum=3),
                    name.casefold(),
                    entity_id,
                    name,
                )
                for label, entity_id, name in labels
                if _eligible_for_edit_distance(label)
            ]
            eligible = [item for item in edit_matches if item[0] <= 3]
        if eligible:
            distance = min(item[0] for item in eligible)
            best = [item for item in eligible if item[0] == distance]
            if len({item[2] for item in best}) != 1:
                return None
            _, _, entity_id, name = min(best, key=lambda item: (item[1], item[2]))
            return Alignment(query, kind, entity_id, name, "edit_distance", float(distance))

        if self.embedder is None or not _eligible_for_semantic_alignment(normalized_query):
            return None
        canonical = sorted(nodes.values(), key=lambda node: (node.name.casefold(), node.entity_id))
        if self.graph.node_embeddings is None:
            vectors = self.embedder.encode([query, *(node.name for node in canonical)])
            if len(vectors) != len(canonical) + 1:
                raise ValueError("embedder returned an unexpected number of vectors")
            query_vector = vectors[0]
            node_vectors = vectors[1:]
        else:
            query_vectors = self.embedder.encode([query])
            if len(query_vectors) != 1:
                raise ValueError("embedder returned an unexpected number of query vectors")
            missing = [
                node.entity_id
                for node in canonical
                if node.entity_id not in self.graph.node_embeddings
            ]
            if missing:
                raise MedKGIAssetError(f"precomputed embeddings are incomplete: {missing}")
            query_vector = query_vectors[0]
            node_vectors = [self.graph.node_embeddings[node.entity_id] for node in canonical]
        similarities = [
            (self._cosine(query_vector, vector), node.name.casefold(), node.entity_id, node.name)
            for node, vector in zip(canonical, node_vectors)
        ]
        score = max(item[0] for item in similarities)
        if score < self.semantic_threshold:
            return None
        tied = [item for item in similarities if math.isclose(item[0], score, abs_tol=1e-12)]
        if len({item[2] for item in tied}) != 1:
            return None
        score, _, entity_id, name = min(tied, key=lambda item: (item[1], item[2]))
        return Alignment(query, kind, entity_id, name, "embedding", score)

    @staticmethod
    def _levenshtein(left: str, right: str, *, maximum: int) -> int:
        if abs(len(left) - len(right)) > maximum:
            return maximum + 1
        previous = list(range(len(right) + 1))
        for left_index, left_char in enumerate(left, start=1):
            current = [left_index]
            for right_index, right_char in enumerate(right, start=1):
                current.append(
                    min(
                        current[-1] + 1,
                        previous[right_index] + 1,
                        previous[right_index - 1] + (left_char != right_char),
                    )
                )
            if min(current) > maximum:
                return maximum + 1
            previous = current
        return previous[-1]

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right) or not left:
            raise ValueError("embedding vectors must have equal non-zero dimensions")
        if any(not math.isfinite(float(value)) for value in (*left, *right)):
            raise ValueError("embedding vectors must contain only finite values")
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
        right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
        if not left_norm or not right_norm:
            raise ValueError("embedding vectors must not be zero vectors")
        return dot / (left_norm * right_norm)

"""AMIE diagnosis-strategy adapter for the local MedKGI decision core.

Only reviewed route profiles and deployed questionnaire facts may enter this
adapter. Posterior values are relative decision weights, not calibrated
disease risk or a clinical diagnosis.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from domain.questionnaires import DISEASE_ROUTES, load_questionnaire_policy
from medkgi import EntityAligner, MedKGIConfig, MedKGICore, OSCEState
from medkgi.loader import MedKGILoader
from medkgi.profile_experiment import (
    build_profile_experiment_graph,
    fact_symptom_id,
    profile_disease_id,
)

from .clinical_facts import FACT_CODES, facts_for_route
from .disease_profiles import load_profile_document, question_fact_codes

METHOD = "medkgi_bayesian_information_gain_v1"
PROFILE_EXPERIMENT_METHOD = "medkgi_profile_clue_experiment_v1"
POSTERIOR_NOTE = "relative_weight_not_calibrated_disease_risk"
PRIVATE_STATE_KEY = "_medkgi_state"
STRICT_GRAPH_MODE = "primekg_strict"
PROFILE_EXPERIMENT_GRAPH_MODE = "profile_experiment"
BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ASSET_DIRECTORY = BACKEND_DIR / "data" / "medkgi"


class MedKGIStrategyError(RuntimeError):
    """Raised when a fully KG-grounded assessment cannot be produced."""


class _LocalPubMedBERTEmbedder:
    """Embed unknown queries locally while serving KG names from the frozen NPZ."""

    def __init__(
        self,
        model_directory: Path,
        cached_vectors: Mapping[str, Sequence[float]],
    ):
        if not cached_vectors:
            raise MedKGIStrategyError(
                "runtime PubMedBERT requires manifest-verified node embeddings"
            )
        self.model_directory = model_directory
        self._vectors = {
            name: tuple(float(value) for value in vector) for name, vector in cached_vectors.items()
        }
        self._tokenizer: Any | None = None
        self._model: Any | None = None

    def _load(self) -> tuple[Any, Any]:
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer, self._model
        try:
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise MedKGIStrategyError(
                "local PubMedBERT alignment requires the Transformers package"
            ) from exc
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_directory),
                local_files_only=True,
                trust_remote_code=False,
            )
            self._model = AutoModel.from_pretrained(
                str(self.model_directory),
                local_files_only=True,
                trust_remote_code=False,
            )
            self._model.eval()
        except Exception as exc:
            raise MedKGIStrategyError(
                f"could not load local PubMedBERT model: {self.model_directory}"
            ) from exc
        return self._tokenizer, self._model

    def _encode_uncached(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        try:
            import torch
        except ImportError as exc:
            raise MedKGIStrategyError(
                "local PubMedBERT alignment requires the PyTorch package"
            ) from exc
        tokenizer, model = self._load()
        tokens = tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=128,
            return_tensors="pt",
        )
        with torch.inference_mode():
            hidden = model(**tokens).last_hidden_state
            mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return [tuple(float(value) for value in row) for row in pooled.cpu().tolist()]

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        missing = list(dict.fromkeys(text for text in texts if text not in self._vectors))
        if missing:
            vectors = self._encode_uncached(missing)
            if len(vectors) != len(missing):
                raise MedKGIStrategyError("local PubMedBERT returned an invalid vector count")
            self._vectors.update(zip(missing, vectors))
        return [self._vectors[text] for text in texts]


class MedKGIDiagnosisStrategy:
    """Adapt MedKGICore outputs to AMIE's existing assessment contract."""

    def __init__(self, core: MedKGICore, *, graph_mode: str = STRICT_GRAPH_MODE):
        if graph_mode not in {STRICT_GRAPH_MODE, PROFILE_EXPERIMENT_GRAPH_MODE}:
            raise ValueError("unsupported MedKGI graph mode")
        self.core = core
        self.graph_mode = graph_mode

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> MedKGIDiagnosisStrategy:
        values = os.environ if env is None else env
        raw_manifest = values.get("MEDKGI_MANIFEST_PATH", "").strip()
        raw_graph = values.get("MEDKGI_KG_PATH", "").strip()
        if raw_manifest:
            manifest_path = cls._configured_path(raw_manifest)
        elif raw_graph:
            manifest_path = cls._configured_path(raw_graph).parent / "manifest.json"
        else:
            manifest_path = DEFAULT_ASSET_DIRECTORY / "manifest.json"
        if raw_graph:
            graph_path = cls._configured_path(raw_graph)
        else:
            graph_path = manifest_path.parent / "primekg.json"

        raw_embeddings = values.get("MEDKGI_EMBEDDINGS_PATH", "").strip()
        embeddings_path = (
            cls._configured_path(raw_embeddings)
            if raw_embeddings
            else cls._manifest_embedding_path(manifest_path)
        )
        raw_max_turns = values.get("MEDKGI_MAX_TURNS", "20").strip()
        try:
            max_turns = int(raw_max_turns)
        except ValueError as exc:
            raise MedKGIStrategyError("MEDKGI_MAX_TURNS must be an integer") from exc
        if not 1 <= max_turns <= 100:
            raise MedKGIStrategyError("MEDKGI_MAX_TURNS must be between 1 and 100")

        raw_model = values.get("MEDKGI_PUBMEDBERT_MODEL", "").strip()
        graph_mode = values.get("MEDKGI_GRAPH_MODE", STRICT_GRAPH_MODE).strip()
        if graph_mode not in {STRICT_GRAPH_MODE, PROFILE_EXPERIMENT_GRAPH_MODE}:
            raise MedKGIStrategyError("MEDKGI_GRAPH_MODE is unsupported")
        if graph_mode == PROFILE_EXPERIMENT_GRAPH_MODE and raw_model:
            raise MedKGIStrategyError(
                "profile experiment uses exact profile IDs, not PubMedBERT alignment"
            )
        model_path = None
        if raw_model:
            if raw_model.startswith("hf://"):
                raise MedKGIStrategyError(
                    "runtime PubMedBERT must be an existing local model directory, not hf://"
                )
            model_path = cls._configured_path(raw_model)
            if not model_path.is_dir():
                raise MedKGIStrategyError(
                    "MEDKGI_PUBMEDBERT_MODEL must be an existing local model directory"
                )

        graph = MedKGILoader.load(graph_path, manifest_path, embeddings_path)
        if graph_mode == PROFILE_EXPERIMENT_GRAPH_MODE:
            documents = {
                route: load_profile_document(route)
                for route in DISEASE_ROUTES
                if load_questionnaire_policy(route)["selection_strategy"] == "disease_vote"
            }
            graph = build_profile_experiment_graph(
                documents, primekg_provenance=graph.provenance, allowed_fact_codes=FACT_CODES
            )
        embedder = None
        if model_path is not None:
            if graph.node_embeddings is None:
                raise MedKGIStrategyError(
                    "runtime PubMedBERT requires manifest-verified node embeddings"
                )
            cached_vectors: dict[str, Sequence[float]] = {}
            for entity_id, node in {**graph.diseases, **graph.symptoms}.items():
                vector = graph.node_embeddings.get(entity_id)
                if vector is None:
                    raise MedKGIStrategyError(
                        f"MedKGI node embedding is missing for entity {entity_id}"
                    )
                cached_vectors.setdefault(node.name, vector)
            embedder = _LocalPubMedBERTEmbedder(model_path, cached_vectors)
        strategy = cls(
            MedKGICore(
                graph,
                aligner=EntityAligner(graph, embedder=embedder),
                config=MedKGIConfig(turn_limit=max_turns),
            ),
            graph_mode=graph_mode,
        )
        strategy.validate_deployed_routes()
        return strategy

    def validate_deployed_routes(self) -> None:
        """Fail before session creation if any active route profile is ungrounded."""
        for route in DISEASE_ROUTES:
            if load_questionnaire_policy(route)["selection_strategy"] != "disease_vote":
                continue
            document = load_profile_document(route)
            profiles = [item for item in document.get("profiles", []) if isinstance(item, dict)]
            if not profiles:
                raise MedKGIStrategyError(f"{route} has no reviewed disease profiles")
            self._aligned_profiles(profiles, route=route)
            self._require_fact_alignment(self._profile_fact_codes(profiles), route=route)

    @staticmethod
    def _configured_path(value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @staticmethod
    def _manifest_embedding_path(manifest_path: Path) -> Path | None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
        embedding = artifacts.get("embeddings") if isinstance(artifacts, dict) else None
        if embedding is None:
            return None
        if not isinstance(embedding, dict):
            raise MedKGIStrategyError("manifest artifacts.embeddings must be an object")
        declared = embedding.get("path")
        if not isinstance(declared, str) or Path(declared).name != declared:
            raise MedKGIStrategyError("manifest embedding path must be a local filename")
        return manifest_path.parent / declared

    @staticmethod
    def _profile_terms(profile: dict[str, Any]) -> list[str]:
        raw_codings = profile.get("coding")
        codings = raw_codings if isinstance(raw_codings, list) else [raw_codings]
        verified_displays = [
            str(coding["display"]).strip()
            for coding in codings
            if isinstance(coding, dict)
            and coding.get("system") == "http://snomed.info/sct"
            and coding.get("verified") is True
            and str(coding.get("display") or "").strip()
        ]
        name = str(profile.get("name") or "").strip()
        return list(dict.fromkeys([*verified_displays, name] if name else verified_displays))

    @staticmethod
    def _profile_fact_codes(profiles: list[dict[str, Any]]) -> set[str]:
        return {
            str(clue["fact"])
            for profile in profiles
            for clue in profile.get("clues", [])
            if isinstance(clue, dict) and clue.get("fact")
        }

    def _aligned_profiles(
        self,
        profiles: list[dict[str, Any]],
        *,
        route: str,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        if self.graph_mode == STRICT_GRAPH_MODE:
            return self._align_profiles(profiles)

        profile_to_disease: dict[str, str] = {}
        disease_to_profile: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            profile_id = str(profile.get("id") or "").strip()
            if not profile_id or profile_id in profile_to_disease:
                raise MedKGIStrategyError("profile experiment requires unique profile IDs")
            disease_id = profile_disease_id(route, profile_id)
            if disease_id not in self.core.graph.diseases:
                raise MedKGIStrategyError(
                    f"profile experiment is missing disease node: {disease_id}"
                )
            if not self.core.graph.symptom_edges(disease_id):
                raise MedKGIStrategyError(
                    f"profile experiment disease has no fact edges: {disease_id}"
                )
            profile_to_disease[profile_id] = disease_id
            disease_to_profile[disease_id] = profile
        if not profile_to_disease:
            raise MedKGIStrategyError("profile experiment has no disease profiles")
        return profile_to_disease, disease_to_profile

    def _align_profiles(
        self,
        profiles: list[dict[str, Any]],
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        profile_to_disease: dict[str, str] = {}
        disease_to_profile: dict[str, dict[str, Any]] = {}
        unmatched: list[str] = []
        for profile in profiles:
            profile_id = str(profile.get("id") or "").strip()
            alignments = [
                match
                for term in self._profile_terms(profile)
                if (match := self.core.aligner.align(term, "disease")) is not None
            ]
            aligned_ids = {item.entity_id for item in alignments}
            if len(aligned_ids) > 1:
                raise MedKGIStrategyError(
                    "reviewed profile terms aligned to conflicting KG diseases: "
                    f"{profile_id or '<missing-profile-id>'}"
                )
            alignment = alignments[0] if alignments else None
            if alignment is not None and not self.core.graph.symptom_edges(alignment.entity_id):
                alignment = None
            if alignment is None:
                unmatched.append(profile_id or "<missing-profile-id>")
                continue
            existing = disease_to_profile.get(alignment.entity_id)
            if existing is not None and existing.get("id") != profile_id:
                raise MedKGIStrategyError(
                    "multiple reviewed profiles aligned to one KG disease: "
                    f"{existing.get('id')} and {profile_id}"
                )
            profile_to_disease[profile_id] = alignment.entity_id
            disease_to_profile[alignment.entity_id] = profile
        if unmatched:
            raise MedKGIStrategyError(
                "reviewed disease profiles could not be aligned to the MedKGI graph: "
                + ", ".join(sorted(unmatched))
            )
        if not profile_to_disease:
            raise MedKGIStrategyError("no reviewed disease profile could be aligned to MedKGI")
        return profile_to_disease, disease_to_profile

    def _fact_alignment(self, codes: set[str]) -> tuple[dict[str, str], list[str]]:
        fact_to_symptom: dict[str, str] = {}
        unmatched: list[str] = []
        for code in sorted(codes):
            if self.graph_mode == PROFILE_EXPERIMENT_GRAPH_MODE:
                symptom_id = fact_symptom_id(code)
                if symptom_id in self.core.graph.symptoms:
                    fact_to_symptom[code] = symptom_id
                else:
                    unmatched.append(code)
                continue
            alignment = self.core.aligner.align(code.replace("_", " "), "symptom")
            if alignment is None:
                unmatched.append(code)
            else:
                fact_to_symptom[code] = alignment.entity_id
        return fact_to_symptom, unmatched

    def _require_fact_alignment(self, codes: set[str], *, route: str) -> dict[str, str]:
        mapping, unmatched = self._fact_alignment(codes)
        if unmatched:
            raise MedKGIStrategyError(
                f"allowlisted {route} clinical facts could not be aligned to MedKGI: "
                + ", ".join(unmatched)
            )
        return mapping

    @staticmethod
    def _restore_osce_state(previous_assessment: dict[str, Any] | None) -> OSCEState:
        private = (
            previous_assessment.get(PRIVATE_STATE_KEY, {})
            if isinstance(previous_assessment, dict)
            else {}
        )
        if not isinstance(private, dict):
            raise MedKGIStrategyError("previous MedKGI private state is invalid")
        history = private.get("candidate_history", [])
        asked = private.get("asked_symptom_ids", [])
        turn_count = private.get("turn_count", 0)
        if (
            not isinstance(history, list)
            or any(
                not isinstance(snapshot, list)
                or any(not isinstance(item, str) for item in snapshot)
                for snapshot in history
            )
            or not isinstance(asked, list)
            or any(not isinstance(item, str) for item in asked)
            or isinstance(turn_count, bool)
            or not isinstance(turn_count, int)
            or turn_count < 0
        ):
            raise MedKGIStrategyError("previous MedKGI OSCE state is invalid")
        return OSCEState(
            candidate_history=tuple(tuple(snapshot) for snapshot in history),
            asked_symptom_ids=tuple(dict.fromkeys(asked)),
            turn_count=turn_count,
        )

    @staticmethod
    def _evidence_rows(
        symptom_ids: tuple[str, ...],
        symptom_to_facts: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        rows = []
        for symptom_id in symptom_ids:
            facts = symptom_to_facts.get(symptom_id, [])
            if facts:
                rows.append(
                    {
                        "fact": facts[0]["code"],
                        "evidence": facts[0]["evidence"],
                        "vote": 1,
                    }
                )
        return rows

    def score_diseases(
        self,
        clinical_facts: list[dict[str, Any]],
        *,
        route: str,
        previous_assessment: dict[str, Any] | None,
    ) -> dict[str, Any]:
        document = load_profile_document(route)
        profiles = [item for item in document.get("profiles", []) if isinstance(item, dict)]
        if not profiles:
            raise MedKGIStrategyError(f"{route} has no reviewed disease profiles")
        profile_to_disease, disease_to_profile = self._aligned_profiles(profiles, route=route)

        route_facts = facts_for_route(clinical_facts, route)
        observed_mapping = self._require_fact_alignment(set(route_facts), route=route)
        query_mapping = self._require_fact_alignment(
            self._profile_fact_codes(profiles), route=route
        )
        fact_to_symptom = {**query_mapping, **observed_mapping}
        approved_symptoms = tuple(sorted(set(query_mapping.values())))

        state = self._restore_osce_state(previous_assessment)
        symptom_to_facts: dict[str, list[dict[str, Any]]] = {}
        statuses: dict[str, str] = {}
        for code, fact in sorted(route_facts.items()):
            symptom_id = observed_mapping.get(code)
            if symptom_id is None:
                continue
            status = "positive" if fact["status"] == "present" else "negative"
            if symptom_id in statuses and statuses[symptom_id] != status:
                raise MedKGIStrategyError(
                    f"conflicting clinical facts align to KG symptom {symptom_id}"
                )
            statuses[symptom_id] = status
            symptom_to_facts.setdefault(symptom_id, []).append(fact)
            state = state.with_observation(
                symptom_id,
                status,
                source_text=str(fact.get("evidence") or ""),
            )

        result = self.core.assess(
            state,
            candidate_ids=tuple(profile_to_disease.values()),
            approved_query_symptom_ids=approved_symptoms,
        )
        if not result.candidates or result.decision.action == "handoff":
            raise MedKGIStrategyError("MedKGI produced no KG-grounded candidate diseases")

        known_codes = set(route_facts)
        ranked = []
        for posterior in result.candidates:
            profile = disease_to_profile.get(posterior.disease_id)
            if profile is None:
                raise MedKGIStrategyError(
                    f"MedKGI returned a disease outside reviewed profiles: {posterior.disease_id}"
                )
            connected = {
                edge.symptom_id
                for edge in self.core.graph.symptom_edges(posterior.disease_id)
                if self.graph_mode == STRICT_GRAPH_MODE or edge.probability != 0.5
            }
            relevant_codes = {
                str(clue["fact"])
                for clue in profile.get("clues", [])
                if isinstance(clue, dict)
                and clue.get("fact") in fact_to_symptom
                and fact_to_symptom[str(clue["fact"])] in connected
            }
            evaluated = relevant_codes & known_codes
            coverage = round(len(evaluated) / len(relevant_codes), 4) if relevant_codes else 0.0
            if self.graph_mode == PROFILE_EXPERIMENT_GRAPH_MODE:
                supporting_ids: list[str] = []
                opposing_ids: list[str] = []
                for symptom_id in sorted(connected & set(statuses)):
                    probability = self.core.graph.edge_probability(
                        posterior.disease_id, symptom_id, self.core.config.smoothing
                    )
                    supports = (statuses[symptom_id] == "positive") == (probability > 0.5)
                    (supporting_ids if supports else opposing_ids).append(symptom_id)
                supporting = self._evidence_rows(tuple(supporting_ids), symptom_to_facts)
                opposing = self._evidence_rows(tuple(opposing_ids), symptom_to_facts)
            else:
                supporting = self._evidence_rows(
                    posterior.supporting_symptom_ids,
                    symptom_to_facts,
                )
                opposing = self._evidence_rows(
                    posterior.contradicting_symptom_ids,
                    symptom_to_facts,
                )
            missing = relevant_codes - known_codes
            if result.decision.action == "final" and not profile.get("must_not_miss"):
                missing = set()
            ranked.append(
                {
                    "id": profile["id"],
                    "name": profile["name"],
                    "coding": profile.get("coding"),
                    "must_not_miss": bool(profile.get("must_not_miss")),
                    "review_status": profile.get("review_status", "provisional"),
                    "safety_rule_codes": list(profile.get("safety_rule_codes", [])),
                    "net_votes": len(supporting) - len(opposing),
                    "support_votes": len(supporting),
                    "oppose_votes": len(opposing),
                    "coverage": coverage,
                    "decisive_coverage": coverage,
                    "supporting": supporting,
                    "opposing": opposing,
                    "missing_facts": sorted(missing),
                    "posterior_weight": posterior.probability,
                    "posterior_interpretation": POSTERIOR_NOTE,
                }
            )

        inquiries = (
            {}
            if result.decision.action == "final"
            else {
                item.symptom_id: {
                    "symptom_name": item.symptom_name,
                    "information_gain": item.information_gain,
                    "marginal_probability": item.marginal_probability,
                    "refutation_margin": item.refutation_margin,
                }
                for item in result.inquiries
                if item.symptom_id in approved_symptoms
            }
        )
        private_state = {
            "candidate_history": [list(snapshot) for snapshot in result.state.candidate_history],
            # Core proposes but does not consume an inquiry. AMIE records only
            # the required/Safety/general question it actually selects below.
            "asked_symptom_ids": list(state.asked_symptom_ids),
            "turn_count": state.turn_count,
            "profile_to_disease": profile_to_disease,
            "fact_to_symptom": fact_to_symptom,
            "unmatched_fact_codes": [],
            "inquiries": inquiries,
            "decision": {
                "action": result.decision.action,
                "reason": result.decision.reason,
                "next_symptom_id": result.decision.next_symptom_id,
            },
        }
        has_evidence = bool(state.evidence)
        return {
            "schema_version": 2,
            "method": (
                PROFILE_EXPERIMENT_METHOD
                if self.graph_mode == PROFILE_EXPERIMENT_GRAPH_MODE
                else METHOD
            ),
            "status": "ready" if has_evidence else "insufficient",
            "computed_from": "live",
            "provisional": self.graph_mode == PROFILE_EXPERIMENT_GRAPH_MODE
            or any(item["review_status"] == "provisional" for item in ranked),
            "posterior_interpretation": POSTERIOR_NOTE,
            "profile_version": document["profile_version"],
            "graph_provenance": {
                "knowledge_graph_version": self.core.graph.provenance.knowledge_graph_version,
                "graph_sha256": self.core.graph.provenance.graph_sha256,
                "source_name": self.core.graph.provenance.source_name,
                "review_status": self.core.graph.provenance.review_status,
            },
            "top": ranked[:5] if has_evidence else [],
            "ranked": ranked,
            "must_not_miss": [item for item in ranked if item["must_not_miss"]],
            PRIVATE_STATE_KEY: private_state,
        }

    def record_selected_question(
        self,
        question: dict[str, Any],
        assessment: dict[str, Any],
        *,
        route: str,
    ) -> dict[str, Any]:
        """Persist only the KG symptoms represented by AMIE's actual selection."""
        del route
        private = assessment.get(PRIVATE_STATE_KEY)
        if not isinstance(private, dict):
            raise MedKGIStrategyError("MedKGI private state is unavailable")
        fact_to_symptom = private.get("fact_to_symptom")
        asked = private.get("asked_symptom_ids")
        turn_count = private.get("turn_count")
        if (
            not isinstance(fact_to_symptom, dict)
            or not isinstance(asked, list)
            or any(not isinstance(item, str) for item in asked)
            or isinstance(turn_count, bool)
            or not isinstance(turn_count, int)
        ):
            raise MedKGIStrategyError("MedKGI selected-question state is invalid")
        selected_symptom_ids = sorted(
            {
                fact_to_symptom[code]
                for code in question_fact_codes(question)
                if isinstance(fact_to_symptom.get(code), str)
            }
        )
        if not selected_symptom_ids:
            return assessment
        updated_private = {
            **private,
            "asked_symptom_ids": list(dict.fromkeys([*asked, *selected_symptom_ids])),
            "turn_count": turn_count + 1,
        }
        return {**assessment, PRIVATE_STATE_KEY: updated_private}

    @staticmethod
    def _question_inquiries(
        question: dict[str, Any],
        container: dict[str, Any],
    ) -> tuple[set[str], list[dict[str, Any]]]:
        private = container.get(PRIVATE_STATE_KEY, {})
        if not isinstance(private, dict):
            return set(), []
        fact_to_symptom = private.get("fact_to_symptom", {})
        inquiries = private.get("inquiries", {})
        if not isinstance(fact_to_symptom, dict) or not isinstance(inquiries, dict):
            return set(), []
        target_codes = {
            code
            for code in question_fact_codes(question)
            if isinstance(fact_to_symptom.get(code), str) and fact_to_symptom[code] in inquiries
        }
        symptom_ids = {fact_to_symptom[code] for code in target_codes}
        return target_codes, [inquiries[item] for item in sorted(symptom_ids)]

    def question_utility(
        self,
        question: dict[str, Any],
        assessment: dict[str, Any],
        *,
        route: str,
    ) -> float:
        del route
        _, inquiries = self._question_inquiries(question, assessment)
        return sum(float(item.get("information_gain") or 0.0) for item in inquiries)

    def build_candidate_frontier(
        self,
        assessment: dict[str, Any],
        *,
        max_candidates: int,
    ) -> dict[str, Any]:
        ranked = [item for item in assessment.get("ranked", []) if item.get("id")]
        candidates = ranked[: max(0, max_candidates)]
        if assessment.get("status") == "insufficient":
            phase = "broad"
            leader_id = None
        else:
            phase = "confirm" if len(candidates) == 1 else "differentiate"
            leader_id = candidates[0]["id"] if candidates else None
        return {
            "phase": phase,
            "leader_id": leader_id,
            "candidates": [
                {
                    "id": item["id"],
                    "name": item.get("name", item["id"]),
                    "net_votes": int(item.get("net_votes") or 0),
                    "support_votes": int(item.get("support_votes") or 0),
                    "coverage": float(item.get("coverage") or 0.0),
                    "posterior_weight": float(item.get("posterior_weight") or 0.0),
                }
                for item in candidates
            ],
            PRIVATE_STATE_KEY: assessment.get(PRIVATE_STATE_KEY, {}),
        }

    def funnel_question_score(
        self,
        question: dict[str, Any],
        frontier: dict[str, Any],
        *,
        route: str,
    ) -> dict[str, Any]:
        del route
        target_codes, inquiries = self._question_inquiries(question, frontier)
        return {
            "discrimination_score": sum(
                float(item.get("information_gain") or 0.0) for item in inquiries
            ),
            "confirmation_score": sum(
                float(item.get("marginal_probability") or 0.0) for item in inquiries
            ),
            "refutation_score": sum(
                max(0.0, float(item.get("refutation_margin") or 0.0)) for item in inquiries
            ),
            "target_fact_codes": sorted(target_codes),
        }

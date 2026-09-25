"""Local MedKGI diagnostic-decision primitives.

This package implements research decision support from the MedKGI paper. It is
not a medical device, does not establish a diagnosis, and requires qualified
clinical review before any patient-care use.
"""

from .core import MedKGIConfig, MedKGICore
from .graph import EntityAligner, KnowledgeGraph, MedKGIAssetError, MedKGIUnavailable
from .loader import MedKGILoader
from .models import (
    Alignment,
    DiagnosticDecision,
    DiseasePosterior,
    EvidenceObservation,
    InquiryCandidate,
    MedKGIResult,
    OSCEState,
)

__all__ = [
    "Alignment",
    "DiagnosticDecision",
    "DiseasePosterior",
    "EntityAligner",
    "EvidenceObservation",
    "InquiryCandidate",
    "KnowledgeGraph",
    "MedKGIAssetError",
    "MedKGIConfig",
    "MedKGICore",
    "MedKGILoader",
    "MedKGIResult",
    "MedKGIUnavailable",
    "OSCEState",
]

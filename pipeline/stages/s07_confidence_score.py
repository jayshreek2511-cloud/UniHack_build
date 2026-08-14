"""
Stage 07 — Per-Record & Per-Field Confidence / Completeness Scoring

Computes a granular completeness score per field AND an overall record score based on:
  1. Phase 2 extracted attribute confidence tags ('source-verified' = 1.0, 'inferred' = 0.85, 'not-found' = 0.0)
  2. Phase 3 manufacturer URL verification status ('source-verified' = 1.0, 'not-found' = 0.0)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from pipeline.stages.s04_attribute_extract import RecordExtractionResult
from pipeline.stages.s05_manufacturer_enrich import ManufacturerSourceInfo

logger = logging.getLogger(__name__)

# Weight mapping by confidence tag
CONFIDENCE_WEIGHTS = {
    "source-verified": 1.0,
    "inferred": 0.85,
    "not-found": 0.0,
}

CRITICAL_FIELDS = {
    "Manufacturer URL",
    "Voltage Rating",
    "Amperage Rating",
    "Sound Level",
    "Mounting Type",
    "Series",
    "Material",
}


@dataclass
class FieldScore:
    field_name: str
    confidence_type: str  # "source-verified" | "inferred" | "not-found"
    score: float
    is_critical: bool
    value: Optional[str]


@dataclass
class RecordConfidenceScore:
    mfg_part_num: str
    overall_score: float
    field_scores: Dict[str, FieldScore]
    critical_missing_count: int
    critical_missing_fields: List[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["field_scores"] = {k: asdict(v) for k, v in self.field_scores.items()}
        return d


def compute_record_confidence(
    extraction: RecordExtractionResult,
    mfr_info: ManufacturerSourceInfo
) -> RecordConfidenceScore:
    """Calculate completeness score per field and overall weighted score for one ProductRecord."""
    field_scores: Dict[str, FieldScore] = {}

    # 1. Score Manufacturer URL & Manufacturer Name (from Phase 3)
    mfr_conf = mfr_info.verification_status
    mfr_score = CONFIDENCE_WEIGHTS.get(mfr_conf, 0.0)
    field_scores["Manufacturer URL"] = FieldScore(
        field_name="Manufacturer URL",
        confidence_type=mfr_conf,
        score=mfr_score,
        is_critical=True,
        value=mfr_info.mfr_url,
    )

    mfr_name_conf = "source-verified" if (mfr_info.real_manufacturer and mfr_info.real_manufacturer != "Unknown") else "not-found"
    field_scores["Manufacturer Name"] = FieldScore(
        field_name="Manufacturer Name",
        confidence_type=mfr_name_conf,
        score=CONFIDENCE_WEIGHTS.get(mfr_name_conf, 0.0),
        is_critical=False,
        value=mfr_info.real_manufacturer,
    )

    # 2. Score Extracted Attributes (from Phase 2)
    for attr_name, attr in extraction.attributes.items():
        conf_type = attr.confidence_source
        score = CONFIDENCE_WEIGHTS.get(conf_type, 0.0)
        is_crit = attr_name in CRITICAL_FIELDS
        field_scores[attr_name] = FieldScore(
            field_name=attr_name,
            confidence_type=conf_type,
            score=score,
            is_critical=is_crit,
            value=attr.value,
        )

    # Calculate overall completeness score
    # Evaluates all critical fields + all populated optional fields to avoid penalizing unpopulated non-applicable schema slots
    total_weight = 0.0
    weighted_sum = 0.0
    critical_missing = []

    for fs in field_scores.values():
        is_populated = fs.value is not None
        # Include field if it is critical OR if it has a populated value
        if fs.is_critical or is_populated:
            w = 2.0 if fs.is_critical else 1.0
            total_weight += w
            weighted_sum += fs.score * w

        if fs.is_critical and (fs.score == 0.0 or not is_populated):
            critical_missing.append(fs.field_name)

    overall_score = round(weighted_sum / total_weight, 3) if total_weight > 0 else 0.0

    return RecordConfidenceScore(
        mfg_part_num=extraction.mfg_part_num,
        overall_score=overall_score,
        field_scores=field_scores,
        critical_missing_count=len(critical_missing),
        critical_missing_fields=critical_missing,
    )


def compute_all_confidence_scores(
    extractions: List[RecordExtractionResult],
    mfr_sources: Dict[str, ManufacturerSourceInfo]
) -> Dict[str, RecordConfidenceScore]:
    """Compute confidence scores for a batch of extraction records."""
    scores: Dict[str, RecordConfidenceScore] = {}
    for ext in extractions:
        mfr_info = mfr_sources.get(
            ext.mfg_part_num,
            ManufacturerSourceInfo(
                mfg_part_num=ext.mfg_part_num,
                real_manufacturer="Unknown",
                real_brand="Unknown",
                mfr_url=None,
                ref_urls=[],
                verification_status="not-found",
                needs_manual_review=True,
            )
        )
        scores[ext.mfg_part_num] = compute_record_confidence(ext, mfr_info)

    logger.info("Computed confidence scores for %d records.", len(scores))
    return scores

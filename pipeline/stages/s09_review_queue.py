"""
Stage 09 — Automated Human Review Queue Router

Evaluates products against completeness and accuracy thresholds:
  1. Overall confidence score threshold (default: 0.75)
  2. Unverified MFR URL (mfr_url is None or needs_manual_review = True)
  3. Description consistency errors (from Stage 06)
  4. Missing critical attributes

Records passing all criteria are marked 'complete'; others route to the human review queue.
Outputs review_queue.json and review_queue.csv in data/output/.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from pipeline.models import ProductRecord
from pipeline.stages.s05_manufacturer_enrich import ManufacturerSourceInfo
from pipeline.stages.s06_describe import GeneratedDescriptions
from pipeline.stages.s07_confidence_score import RecordConfidenceScore

logger = logging.getLogger(__name__)

DEFAULT_SCORE_THRESHOLD = 0.75


@dataclass
class ReviewQueueItem:
    mfg_part_num: str
    row_index: int
    overall_score: float
    status: str  # "complete" | "needs_review"
    flag_reasons: List[str]
    flagged_fields: List[str]
    mfr_url: Optional[str]
    consistency_passed: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviewQueueBatchResult:
    total_processed: int
    complete_count: int
    review_count: int
    complete_items: List[ReviewQueueItem]
    review_items: List[ReviewQueueItem]


def evaluate_record_for_review(
    record: ProductRecord,
    confidence: RecordConfidenceScore,
    mfr_info: ManufacturerSourceInfo,
    descriptions: GeneratedDescriptions,
    threshold: float = DEFAULT_SCORE_THRESHOLD
) -> ReviewQueueItem:
    """Evaluate one ProductRecord and determine if it requires human review."""
    reasons = []
    flagged_fields = []

    # 1. Check score threshold
    if confidence.overall_score < threshold:
        reasons.append(f"Overall confidence score ({confidence.overall_score:.2f}) below threshold ({threshold:.2f})")

    # 2. Check Manufacturer URL verification
    if not mfr_info.mfr_url or mfr_info.needs_manual_review or mfr_info.verification_status == "not-found":
        reasons.append(f"Unverified Manufacturer URL (HTTP status: {mfr_info.http_status_code or 'N/A'})")
        flagged_fields.append("Manufacturer URL")

    # 3. Check Description Spec Consistency
    if not descriptions.consistency_passed:
        reasons.append(f"Description consistency check failed: {'; '.join(descriptions.consistency_errors)}")

    # 4. Check Critical Missing Fields
    if confidence.critical_missing_fields:
        for f in confidence.critical_missing_fields:
            if f not in flagged_fields:
                flagged_fields.append(f)
        reasons.append(f"Missing critical fields: {', '.join(confidence.critical_missing_fields)}")

    is_complete = len(reasons) == 0
    status = "complete" if is_complete else "needs_review"

    return ReviewQueueItem(
        mfg_part_num=record.mfg_part_num,
        row_index=record.row_index,
        overall_score=confidence.overall_score,
        status=status,
        flag_reasons=reasons,
        flagged_fields=flagged_fields,
        mfr_url=mfr_info.mfr_url,
        consistency_passed=descriptions.consistency_passed,
    )


def process_review_queue(
    records: List[ProductRecord],
    confidences: Dict[str, RecordConfidenceScore],
    mfr_sources: Dict[str, ManufacturerSourceInfo],
    descriptions: Dict[str, GeneratedDescriptions],
    output_dir: Path,
    threshold: float = DEFAULT_SCORE_THRESHOLD
) -> ReviewQueueBatchResult:
    """Process a batch of records, write review_queue outputs, and return summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    complete_list = []
    review_list = []

    for rec in records:
        sku = rec.mfg_part_num
        conf = confidences[sku]
        mfr = mfr_sources[sku]
        desc = descriptions[sku]

        item = evaluate_record_for_review(rec, conf, mfr, desc, threshold=threshold)
        if item.status == "complete":
            complete_list.append(item)
        else:
            review_list.append(item)

    total = len(records)
    logger.info("Review queue evaluation: %d total, %d complete, %d routed to review queue.", total, len(complete_list), len(review_list))

    # 1. Write review_queue.json
    json_path = output_dir / "review_queue.json"
    json_data = {
        "summary": {
            "total_processed": total,
            "complete_count": len(complete_list),
            "review_count": len(review_list),
            "threshold": threshold,
        },
        "review_queue": [item.to_dict() for item in review_list],
        "complete": [item.to_dict() for item in complete_list],
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2)
    logger.info("Wrote review queue JSON -> %s", json_path)

    # 2. Write review_queue.csv
    csv_path = output_dir / "review_queue.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Mfg_Part_Num", "Row_Index", "Overall_Score", "Status",
            "Flagged_Fields", "Flag_Reasons", "MFR_URL", "Consistency_Passed"
        ])
        for item in review_list:
            writer.writerow([
                item.mfg_part_num,
                item.row_index,
                f"{item.overall_score:.3f}",
                item.status,
                "; ".join(item.flagged_fields),
                "; ".join(item.flag_reasons),
                item.mfr_url or "None",
                item.consistency_passed,
            ])
    logger.info("Wrote review queue CSV -> %s", csv_path)

    return ReviewQueueBatchResult(
        total_processed=total,
        complete_count=len(complete_list),
        review_count=len(review_list),
        complete_items=complete_list,
        review_items=review_list,
    )

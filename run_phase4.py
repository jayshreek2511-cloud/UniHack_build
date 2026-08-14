"""
run_phase4.py — Complete End-to-End Pipeline Execution & Phase 4 Validation

Executes:
  - Phase 1: Ingestion & Classification (s01_ingest, s02_classify)
  - Phase 2: Manufacturer Normalization & Attribute Extraction (s03_manufacturer_normalize, s04_attribute_extract)
  - Phase 3: Manufacturer Enrichment & 5-Description Generation (s05_manufacturer_enrich, s06_describe)
  - Phase 4: Confidence Scoring, Provenance Capture, & Review Queue (s07_confidence_score, s08_provenance, s09_review_queue)

Outputs review queue artifacts to data/output/ and prints full audit metrics.
"""

import json
import logging
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.stages.s01_ingest import ingest
from pipeline.stages.s02_classify import classify
from pipeline.stages.s03_manufacturer_normalize import normalize_manufacturers
from pipeline.stages.s04_attribute_extract import extract_attributes
from pipeline.stages.s05_manufacturer_enrich import enrich_manufacturer_sources
from pipeline.stages.s06_describe import generate_descriptions
from pipeline.stages.s07_confidence_score import compute_all_confidence_scores
from pipeline.stages.s08_provenance import build_all_provenance
from pipeline.stages.s09_review_queue import process_review_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("phase4_runner")


def main():
    if len(sys.argv) > 1 and sys.argv[1]:
        input_csv = Path(sys.argv[1])
    else:
        input_csv = PROJECT_ROOT / "data" / "input" / "Unihack__Sample_Dataset_-_Input__1_.csv"

    output_dir = PROJECT_ROOT / "data" / "output"
    ref_dir = PROJECT_ROOT / "pipeline" / "reference"

    logger.info("=" * 90)
    logger.info("STARTING FULL PIPELINE EXECUTION")
    logger.info("TARGET INPUT FILE: %s", input_csv.resolve())
    logger.info("=" * 90)

    # 1. Ingest
    records = ingest(input_csv)
    logger.info("PIPELINE INGESTED %d TOTAL ROWS FROM %s", len(records), input_csv.name)

    # 2. Stage 03: Manufacturer Normalization
    normalize_manufacturers(records, reference_dir=ref_dir)

    # 3. Stage 02: Classify & Isolate Dishwashers
    classify(records)
    dishwasher_records = [r for r in records if r.is_dishwasher]

    # 4. Stage 04: Attribute Extraction
    extraction_results = extract_attributes(dishwasher_records, reference_dir=ref_dir)

    # 5. Stage 05: Manufacturer Enrichment (Browser HTTP Verified Engine)
    mfr_sources = enrich_manufacturer_sources(dishwasher_records)

    # 6. Stage 06: Five-Description Generation & Consistency Verification
    generated_descs = {}
    for rec in dishwasher_records:
        ext = next(r for r in extraction_results if r.mfg_part_num == rec.mfg_part_num)
        mfr_info = mfr_sources[rec.mfg_part_num]
        descs = generate_descriptions(rec, ext, mfr_info)
        generated_descs[rec.mfg_part_num] = descs

    # 7. Stage 07: Per-Record Confidence Scoring
    confidence_scores = compute_all_confidence_scores(extraction_results, mfr_sources)

    # 8. Stage 08: Provenance Lineage Capture
    provenance_records = build_all_provenance(dishwasher_records, extraction_results, mfr_sources)

    # 9. Stage 09: Human Review Queue Router
    batch_result = process_review_queue(
        records=dishwasher_records,
        confidences=confidence_scores,
        mfr_sources=mfr_sources,
        descriptions=generated_descs,
        output_dir=output_dir,
        threshold=0.75,
    )

    # Save full enriched JSON database
    enriched_db = []
    for rec in dishwasher_records:
        sku = rec.mfg_part_num
        item = {
            "identity": rec.to_dict(),
            "extraction": next(e for e in extraction_results if e.mfg_part_num == sku).to_dict(),
            "manufacturer_info": mfr_sources[sku].__dict__,
            "descriptions": generated_descs[sku].to_dict(),
            "confidence_score": confidence_scores[sku].to_dict(),
            "provenance": provenance_records[sku].to_dict(),
        }
        enriched_db.append(item)

    enriched_json_path = output_dir / "dishwasher_enriched_full.json"
    with open(enriched_json_path, "w", encoding="utf-8") as f:
        json.dump(enriched_db, f, indent=2)
    logger.info("Saved full enriched records database -> %s", enriched_json_path)

    # ── PRINT PHASE 4 SUMMARY & METRICS
    print("\n" + "=" * 95)
    print("PHASE 4 REVIEW QUEUE & CONFIDENCE METRICS")
    print("=" * 95)

    comp_pct = (batch_result.complete_count / batch_result.total_processed * 100) if batch_result.total_processed > 0 else 0.0
    rev_pct = (batch_result.review_count / batch_result.total_processed * 100) if batch_result.total_processed > 0 else 0.0
    print(f"Marked COMPLETE (Pass Threshold)  : {batch_result.complete_count} / {batch_result.total_processed} ({comp_pct:.1f}%)")
    print(f"Routed to HUMAN REVIEW QUEUE      : {batch_result.review_count} / {batch_result.total_processed} ({rev_pct:.1f}%)")

    print("\n" + "-" * 95)
    print("COMPLETE RECORDS (PASS ALL CRITERIA & THRESHOLDS)")
    print("-" * 95)
    print(f"{'SKU':<14} | {'Overall Score':<14} | {'Status':<10} | {'MFR URL'}")
    print("-" * 95)
    for item in batch_result.complete_items:
        print(f"{item.mfg_part_num:<14} | {item.overall_score:<14.3f} | {item.status:<10} | {item.mfr_url}")

    print("\n" + "-" * 95)
    print("REVIEW QUEUE RECORDS (FLAGGED FOR HUMAN AUDIT)")
    print("-" * 95)
    for item in batch_result.review_items:
        print(f"\nSKU: {item.mfg_part_num} (Row {item.row_index}) | Overall Score: {item.overall_score:.3f} | MFR URL: {item.mfr_url or 'None'}")
        print("  Flagged Fields:")
        for f in item.flagged_fields:
            print(f"    - {f}")
        print("  Flag Reasons:")
        for r in item.flag_reasons:
            print(f"    - {r}")

    # Display sample provenance for a record
    if provenance_records:
        sample_sku = list(provenance_records.keys())[0]
        sample_prov = provenance_records[sample_sku]
        print("\n" + "=" * 95)
        print(f"SAMPLE PROVENANCE LINEAGE AUDIT (SKU: {sample_sku})")
        print("=" * 95)
        for fname, pentry in list(sample_prov.field_provenance.items())[:6]:
            print(f"Field: {fname:<22} | Value: {str(pentry.value):<20} | Source: {pentry.source_type:<25} | URL: {pentry.source_url or 'N/A'}")

    print("\n" + "=" * 95)
    print("PHASE 4 EXECUTION COMPLETE")
    print("=" * 95 + "\n")


if __name__ == "__main__":
    main()

"""
Diagnostic runner — boundary row-counts + swallowed-exception audit.

Mirrors run_phase4.py stage order, but prints the row count entering and
leaving every stage, runs Stage 10 export in-memory, and re-raises (with
traceback) any exception a stage swallows so nothing is hidden.

Usage: py scripts/diagnose_pipeline.py [input_csv]
"""

import json
import logging
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("diag")

from pipeline.stages.s01_ingest import ingest
from pipeline.stages.s02_classify import classify
from pipeline.stages.s03_manufacturer_normalize import normalize_manufacturers
from pipeline.stages.s04_attribute_extract import extract_attributes
from pipeline.stages.s05_manufacturer_enrich import enrich_manufacturer_sources
from pipeline.stages.s06_describe import generate_descriptions
from pipeline.stages.s07_confidence_score import compute_all_confidence_scores
from pipeline.stages.s08_provenance import build_all_provenance
from pipeline.stages.s09_review_queue import process_review_queue
from pipeline.stages.s10_delivery_export import export_delivery_pipeline

BOUNDARIES = []


def boundary(label: str, n: int):
    BOUNDARIES.append((label, n))
    print(f"[BOUNDARY] {label:<34} n={n}")


def main():
    input_csv = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if input_csv is None:
        input_csv = PROJECT_ROOT / "data" / "input" / "Unihack__Sample_Dataset_-_Input__1_.csv"
    output_dir = PROJECT_ROOT / "data" / "output"
    ref_dir = PROJECT_ROOT / "pipeline" / "reference"

    print("=" * 70)
    print(f"DIAGNOSTIC RUN on: {input_csv.name}")
    print("=" * 70)

    # 1. Ingest
    records = ingest(input_csv)
    boundary("after ingest", len(records))
    uncat_before = sum(1 for r in records if not r.is_dishwasher and r.coarse_category == "Uncategorized")

    # 2. Stage 03: Manufacturer Normalization
    try:
        normalize_manufacturers(records, reference_dir=ref_dir)
        boundary("after manufacturer normalize", len(records))
    except Exception:
        print("[EXC] normalize_manufacturers raised:")
        traceback.print_exc()

    # 3. Stage 02: Classify
    try:
        report = classify(records)
        boundary("after classify", len(records))
        print(f"   classify report: llm={report.llm_classified_count} rule={report.rule_based_count} "
              f"dishwashers={report.dishwasher_count} uncategorized={len(report.uncategorized_records)}")
    except Exception:
        print("[EXC] classify raised:")
        traceback.print_exc()
        sys.exit(1)

    dishwasher_records = [r for r in records if r.is_dishwasher]
    boundary("isolate dishwashers", len(dishwasher_records))

    # 4. Stage 04: Attribute Extraction
    try:
        extraction_results = extract_attributes(dishwasher_records, reference_dir=ref_dir)
        boundary("after attribute extraction", len(extraction_results))
    except Exception:
        print("[EXC] extract_attributes raised:")
        traceback.print_exc()
        sys.exit(1)

    # 5. Stage 05: Manufacturer Enrichment
    try:
        mfr_sources = enrich_manufacturer_sources(dishwasher_records)
        boundary("after manufacturer enrichment", len(mfr_sources))
    except Exception:
        print("[EXC] enrich_manufacturer_sources raised:")
        traceback.print_exc()
        sys.exit(1)

    # 6. Stage 06: Description Generation
    generated_descs = {}
    try:
        for rec in dishwasher_records:
            ext = next(r for r in extraction_results if r.mfg_part_num == rec.mfg_part_num)
            mfr_info = mfr_sources[rec.mfg_part_num]
            generated_descs[rec.mfg_part_num] = generate_descriptions(rec, ext, mfr_info)
        boundary("after description generation", len(generated_descs))
    except Exception:
        print("[EXC] generate_descriptions raised:")
        traceback.print_exc()
        sys.exit(1)

    # 7. Stage 07: Confidence Scoring
    try:
        confidence_scores = compute_all_confidence_scores(extraction_results, mfr_sources)
        boundary("after confidence scoring", len(confidence_scores))
    except Exception:
        print("[EXC] compute_all_confidence_scores raised:")
        traceback.print_exc()
        sys.exit(1)

    # 8. Stage 08: Provenance
    try:
        provenance_records = build_all_provenance(dishwasher_records, extraction_results, mfr_sources)
        boundary("after provenance", len(provenance_records))
    except Exception:
        print("[EXC] build_all_provenance raised:")
        traceback.print_exc()
        sys.exit(1)

    # 9. Stage 09: Review Queue
    try:
        batch_result = process_review_queue(
            records=dishwasher_records,
            confidences=confidence_scores,
            mfr_sources=mfr_sources,
            descriptions=generated_descs,
            output_dir=output_dir,
            threshold=0.75,
        )
        boundary("after review queue", batch_result.total_processed)
        print(f"   review queue: complete={batch_result.complete_count} review={batch_result.review_count}")
    except Exception:
        print("[EXC] process_review_queue raised:")
        traceback.print_exc()
        sys.exit(1)

    # Build enriched DB (same as run_phase4.py)
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
    boundary("enriched_db built (in-memory)", len(enriched_db))

    # 10. Stage 10: Delivery Export
    try:
        df = export_delivery_pipeline(enriched_db, template_path=ref_dir.parent / "input" / "Unihack__Expected_Output_-_Delivery_Format.csv")
        boundary("after delivery export (in-memory df)", len(df))
    except Exception:
        print("[EXC] export_delivery_pipeline raised:")
        traceback.print_exc()
        sys.exit(1)

    print()
    print("=" * 70)
    print("STAGE BOUNDARY SUMMARY")
    print("=" * 70)
    for label, n in BOUNDARIES:
        print(f"  {label:<34} {n}")
    print("=" * 70)
    print("DIAGNOSTIC COMPLETE")


if __name__ == "__main__":
    main()

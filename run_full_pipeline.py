"""
run_full_pipeline.py — Full Pipeline Execution for All Categories

Runs the complete pipeline (S01→S10) on all categories, not just dishwashers.
Generates comprehensive reports including:
  - Category breakdown
  - Sample extracted records from new categories
  - Manufacturer normalization cluster count
  - messy_distributor_test_data.csv results
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
from pipeline.stages.s10_delivery_export import export_delivery_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("full_pipeline")


def main():
    input_csv = PROJECT_ROOT / "data" / "input" / "Unihack__Sample_Dataset_-_Input__1_.csv"
    if len(sys.argv) > 1:
        input_csv = Path(sys.argv[1]).resolve()
    messy_csv = PROJECT_ROOT / "data" / "input" / "messy_distributor_test_data.csv"
    output_dir = PROJECT_ROOT / "data" / "output"
    ref_dir = PROJECT_ROOT / "pipeline" / "reference"

    output_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("FULL PIPELINE EXECUTION — ALL CATEGORIES")
    print("=" * 80)
    print(f"Input: {input_csv}")
    print(f"Output: {output_dir}")
    print("=" * 80)

    # 1. Ingest
    logger.info(">> Stage 01: Ingesting %s", input_csv)
    records = ingest(input_csv)
    print(f"\n[OK] Ingested {len(records)} records")

    # 2. Stage 03: Manufacturer Normalization
    logger.info(">> Stage 03: Normalizing manufacturers")
    norm_report = normalize_manufacturers(records, reference_dir=ref_dir)
    print(f"[OK] Manufacturer normalization: {norm_report.raw_unique_values} raw -> {norm_report.clusters_formed} clusters")

    # Read cluster count
    mfr_json_path = ref_dir / "manufacturer_list.json"
    cluster_count = 0
    if mfr_json_path.exists():
        with open(mfr_json_path, "r", encoding="utf-8") as f:
            mfr_data = json.load(f)
            cluster_count = len(mfr_data.get("clusters", {}))

    # 3. Stage 02: Classify (LLM-primary, rule-based fallback)
    logger.info(">> Stage 02: Classifying records")
    report = classify(records, llm_batch_size=60, llm_max_workers=3)
    report.print_summary()

    # Save classified full dataset for cross-checking
    classified_df = pd.DataFrame([r.to_dict() for r in records])
    classified_path = output_dir / "classified_full.csv"
    classified_df.to_csv(classified_path, index=False)
    logger.info("Saved classified full dataset -> %s", classified_path)

    # Isolate all records for attribute extraction (not just dishwashers)
    all_records = records
    dishwasher_records = [r for r in records if r.is_dishwasher]
    non_dishwasher_records = [r for r in records if not r.is_dishwasher]

    print(f"Dishwasher rows: {len(dishwasher_records)}")
    print(f"Non-dishwasher rows: {len(non_dishwasher_records)}")

    # 4. Stage 04: Attribute Extraction for ALL records (batched dynamic schemas)
    logger.info(">> Stage 04: Extracting attributes for all %d records...", len(all_records))
    extraction_results = extract_attributes(all_records, reference_dir=ref_dir, llm_batch_size=20, llm_max_workers=3)
    print(f"[OK] Extracted attributes for {len(extraction_results)} records")

    # Save full-category extraction database (not just dishwashers)
    extraction_db_path = output_dir / "all_categories_extraction.json"
    with open(extraction_db_path, "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in extraction_results], f, indent=2, ensure_ascii=False)
    logger.info("Saved all-categories extraction database -> %s", extraction_db_path)

    # 5. Stage 05: Manufacturer Enrichment (all records; dishwashers keep appliance-specific URL templates)
    logger.info(">> Stage 05: Enriching manufacturers for %d records...", len(all_records))
    mfr_sources = enrich_manufacturer_sources(all_records)

    # 6. Stage 06: Description Generation (all records; dishwashers keep their specific templates)
    logger.info(">> Stage 06: Generating descriptions for %d records...", len(all_records))
    generated_descs = {}
    for rec in all_records:
        sku = rec.mfg_part_num
        ext = next((r for r in extraction_results if r.mfg_part_num == sku), None)
        mfr_info = mfr_sources.get(sku)
        if ext and mfr_info:
            descs = generate_descriptions(rec, ext, mfr_info)
            generated_descs[sku] = descs

    # 7. Stage 07: Confidence Scoring (all records)
    logger.info(">> Stage 07: Computing confidence scores...")
    confidence_scores = compute_all_confidence_scores(extraction_results, mfr_sources)

    # 8. Stage 08: Provenance (all records)
    logger.info(">> Stage 08: Building provenance records...")
    provenance_records = build_all_provenance(all_records, extraction_results, mfr_sources)

    # 9. Stage 09: Review Queue (all records)
    logger.info(">> Stage 09: Processing review queue...")
    batch_result = process_review_queue(
        records=all_records,
        confidences=confidence_scores,
        mfr_sources=mfr_sources,
        descriptions=generated_descs,
        output_dir=output_dir,
        threshold=0.75,
    )

    # 10. Save enriched database (all records)
    enriched_db = []
    for rec in all_records:
        sku = rec.mfg_part_num
        ext = next((e for e in extraction_results if e.mfg_part_num == sku), None)
        mfr_info = mfr_sources.get(sku)
        if ext and mfr_info:
            item = {
                "identity": rec.to_dict(),
                "extraction": ext.to_dict(),
                "manufacturer_info": mfr_info.__dict__,
                "descriptions": generated_descs[sku].to_dict() if sku in generated_descs else {},
                "confidence_score": confidence_scores[sku].to_dict() if sku in confidence_scores else {},
                "provenance": provenance_records[sku].to_dict() if sku in provenance_records else {},
            }
            enriched_db.append(item)

    enriched_json_path = output_dir / "dishwasher_enriched_full.json"
    with open(enriched_json_path, "w", encoding="utf-8") as f:
        json.dump(enriched_db, f, indent=2)
    logger.info("Saved all-categories enriched database -> %s", enriched_json_path)

    # 11. Stage 10: Delivery Export (all records)
    logger.info(">> Stage 10: Exporting delivery format...")
    export_delivery_pipeline(enriched_db)

    # ── REPORTS ──────────────────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("FULL PIPELINE RESULTS")
    print("=" * 80)

    # Category breakdown
    print(f"\nTotal records processed: {len(records)}")
    print(f"Categories found: {len(report.category_counts)}")
    print(f"Manufacturer clusters: {cluster_count}")
    print(f"\nCategory breakdown:")
    for cat, count in sorted(report.category_counts.items(), key=lambda x: -x[1]):
        pct = count / len(records) * 100 if records else 0
        print(f"  {cat:<50} {count:>5}  ({pct:5.1f}%)")

    print(f"\nUncategorized rows: {len(report.uncategorized_records)}")
    print(f"LLM-classified rows: {report.llm_classified_count}")
    print(f"Rule-based fallback rows: {report.rule_based_count}")

    # Sample records from 3+ non-dishwasher categories
    print("\n" + "=" * 80)
    print("SAMPLE EXTRACTED RECORDS FROM NEW CATEGORIES")
    print("=" * 80)

    non_dishwasher_cats = [
        cat for cat in report.category_counts.keys()
        if "Dishwasher" not in cat and cat != "Uncategorized"
    ]
    # Pick categories that actually produced extracted attributes
    sample_candidates = []
    for cat in non_dishwasher_cats:
        cat_results = [r for r in extraction_results if r.coarse_category == cat]
        if cat_results:
            sample_candidates.append((cat, cat_results))
    sample_cats = sample_candidates[:3]

    for cat, cat_results in sample_cats:
        print(f"\n--- Category: {cat} ---")
        for res in cat_results[:2]:
            print(f"SKU: {res.mfg_part_num}")
            print(f"Desc: {res.part_desc[:100]}")
            print(f"Brand: {res.real_brand} | Mfr: {res.real_manufacturer} | Method: {res.classification_method}")
            print(f"Attributes extracted ({len(res.attributes)}):")
            for label, attr in list(res.attributes.items())[:10]:
                print(f"  {label}: {attr.value} ({attr.confidence_source})")
            if len(res.attributes) > 10:
                print(f"  ... and {len(res.attributes) - 10} more")
            print()

    # Dishwasher metrics
    print("\n" + "=" * 80)
    print("DISHWASHER PIPELINE METRICS (Backward Compatibility Check)")
    print("=" * 80)
    print(f"Dishwasher rows processed: {len(dishwasher_records)}")
    print(f"Complete (pass threshold): {batch_result.complete_count}")
    print(f"Routed to review queue: {batch_result.review_count}")

    # Run messy_distributor_test_data.csv
    print("\n" + "=" * 80)
    print("MESSY DISTRIBUTOR TEST DATA RESULTS")
    print("=" * 80)
    if messy_csv.exists():
        messy_records = ingest(messy_csv)
        print(f"Messy test rows ingested: {len(messy_records)}")

        # Classify (LLM-primary)
        messy_report = classify(messy_records, llm_batch_size=60, llm_max_workers=3)
        messy_categorized = sum(1 for r in messy_records if r.coarse_category != "Uncategorized")
        messy_llm = sum(1 for r in messy_records if r.classification_method == "llm-classified")
        print(f"Messy rows categorized: {messy_categorized}/{len(messy_records)}")
        print(f"  - of which LLM-classified: {messy_llm}")
        print(f"Messy rows uncategorized: {len(messy_records) - messy_categorized}/{len(messy_records)}")
        print(f"\nMessy category breakdown:")
        for cat, count in sorted(messy_report.category_counts.items(), key=lambda x: -x[1]):
            print(f"  {cat:<50} {count:>5}")

        # Extract attributes (batched dynamic schemas)
        messy_extractions = extract_attributes(messy_records, llm_batch_size=20, llm_max_workers=3)
        messy_with_attrs = sum(1 for e in messy_extractions if e.attributes)
        messy_total_attrs = sum(len(e.attributes) for e in messy_extractions)
        print(f"\nMessy rows with extracted attributes: {messy_with_attrs}/{len(messy_extractions)}")
        print(f"Total attribute values extracted across messy rows: {messy_total_attrs}")

        # Save messy results
        messy_df = pd.DataFrame([r.to_dict() for r in messy_records])
        messy_path = output_dir / "messy_distributor_results.csv"
        messy_df.to_csv(messy_path, index=False)
        messy_json_path = output_dir / "messy_distributor_extraction.json"
        with open(messy_json_path, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in messy_extractions], f, indent=2, ensure_ascii=False)
        print(f"Messy results saved -> {messy_path}")
        print(f"Messy extraction saved -> {messy_json_path}")
    else:
        print(f"Messy test file not found at {messy_csv}")

    print("\n" + "=" * 80)
    print("PIPELINE EXECUTION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()

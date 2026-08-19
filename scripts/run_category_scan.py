"""
scripts/run_category_scan.py — Fast category-generalization scan (Stages 01-04 only).

Runs ingestion, manufacturer normalization, LLM-primary classification, and
category-agnostic attribute extraction over the full 1,000-row dataset plus the
messy_distributor_test_data.csv. Skips the dishwasher-only stages 05-10 (live HTTP
manufacturer enrichment / delivery export) which are scoped and already verified.

Usage:
    set GEMINI_API_KEY=...
    py scripts/run_category_scan.py
"""

import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.stages.s01_ingest import ingest
from pipeline.stages.s02_classify import classify
from pipeline.stages.s03_manufacturer_normalize import normalize_manufacturers
from pipeline.stages.s04_attribute_extract import extract_attributes

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("category_scan")


def main():
    input_csv = PROJECT_ROOT / "data" / "input" / "Unihack__Sample_Dataset_-_Input__1_.csv"
    messy_csv = PROJECT_ROOT / "data" / "input" / "messy_distributor_test_data.csv"
    output_dir = PROJECT_ROOT / "data" / "output"
    ref_dir = PROJECT_ROOT / "pipeline" / "reference"
    output_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # ── 1. Ingest + normalize manufacturers ────────────────────────────────
    records = ingest(input_csv)
    norm_report = normalize_manufacturers(records, reference_dir=ref_dir)
    print(f"[OK] Ingested {len(records)} records")
    print(f"[OK] Manufacturer normalization: {norm_report.raw_unique_values} raw -> {norm_report.clusters_formed} clusters")

    # ── 2. Classify (LLM-primary, all rows) ────────────────────────────────
    report = classify(records, llm_batch_size=60, llm_max_workers=3)
    report.print_summary()

    classified_df = pd.DataFrame([r.to_dict() for r in records])
    classified_df.to_csv(output_dir / "classified_full.csv", index=False)

    # ── 3. Attribute extraction (batched dynamic schemas, all categories) ──
    extraction_results = extract_attributes(records, reference_dir=ref_dir, llm_batch_size=20, llm_max_workers=3)
    print(f"[OK] Extracted attributes for {len(extraction_results)} records")

    with open(output_dir / "all_categories_extraction.json", "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in extraction_results], f, indent=2, ensure_ascii=False)

    # ── 4. Report ──────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("CATEGORY BREAKDOWN — FULL 1000-ROW DATASET")
    print("=" * 80)
    print(f"Total records: {len(records)}")
    print(f"Distinct categories: {len(report.category_counts)}")
    print(f"LLM-classified: {report.llm_classified_count} | Rule-based fallback: {report.rule_based_count}")
    for cat, count in sorted(report.category_counts.items(), key=lambda x: -x[1]):
        pct = count / len(records) * 100 if records else 0
        print(f"  {cat:<55} {count:>4}  ({pct:5.1f}%)")

    print(f"\nGenuinely uncategorized: {len(report.uncategorized_records)}")
    if report.uncategorized_records:
        for item in report.uncategorized_records[:12]:
            print(f"    row {item['row_index']}: {item['part_desc'][:80]}")
        if len(report.uncategorized_records) > 12:
            print(f"    ... and {len(report.uncategorized_records) - 12} more")

    # Sample records from 3 new categories
    print("\n" + "=" * 80)
    print("SAMPLE RECORDS FROM 3 NEW CATEGORIES")
    print("=" * 80)
    sample_candidates = []
    for cat in sorted(report.category_counts.keys()):
        if "Dishwasher" in cat or cat == "Uncategorized":
            continue
        cat_results = [r for r in extraction_results if r.coarse_category == cat]
        if cat_results:
            sample_candidates.append((cat, cat_results))
    for cat, cat_results in sample_candidates[:3]:
        print(f"\n--- {cat} ---")
        for res in cat_results[:2]:
            print(f"  SKU: {res.mfg_part_num}")
            print(f"  Desc: {res.part_desc[:110]}")
            print(f"  Method: {res.classification_method}")
            for label, attr in list(res.attributes.items())[:10]:
                uom = f" [{attr.uom}]" if attr.uom else ""
                print(f"    {label}: {attr.value}{uom}  ({attr.confidence_source})")
            if len(res.attributes) > 10:
                print(f"    ... and {len(res.attributes) - 10} more")

    # ── 5. Messy distributor test ──────────────────────────────────────────
    print("\n" + "=" * 80)
    print("MESSY DISTRIBUTOR TEST DATA")
    print("=" * 80)
    if messy_csv.exists():
        messy_records = ingest(messy_csv)
        messy_report = classify(messy_records, llm_batch_size=60, llm_max_workers=3)
        messy_categorized = sum(1 for r in messy_records if r.coarse_category != "Uncategorized")
        messy_llm = sum(1 for r in messy_records if r.classification_method == "llm-classified")
        print(f"Rows ingested: {len(messy_records)}")
        print(f"Classified: {messy_categorized}/{len(messy_records)}  (LLM-classified: {messy_llm})")
        for cat, count in sorted(messy_report.category_counts.items(), key=lambda x: -x[1]):
            print(f"  {cat:<55} {count:>4}")

        messy_extractions = extract_attributes(messy_records, llm_batch_size=20, llm_max_workers=3)
        messy_with_attrs = sum(1 for e in messy_extractions if e.attributes)
        messy_total_attrs = sum(len(e.attributes) for e in messy_extractions)
        print(f"\nExtracted attributes: {messy_with_attrs}/{len(messy_extractions)} rows had attributes")
        print(f"Total attribute values across messy rows: {messy_total_attrs}")

        messy_df = pd.DataFrame([r.to_dict() for r in messy_records])
        messy_df.to_csv(output_dir / "messy_distributor_results.csv", index=False)
        with open(output_dir / "messy_distributor_extraction.json", "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in messy_extractions], f, indent=2, ensure_ascii=False)
        print(f"Messy results -> {output_dir / 'messy_distributor_results.csv'}")

    print(f"\nElapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

"""
TASK 1 EVIDENCE — full pipeline on a mixed-category file, row counts at every
stage boundary, ALL categories combined. Mirrors run_full_pipeline.py stage
calls exactly (same functions, same order), but writes nothing that would
clobber the 1000-row scan artifacts (classified_full.csv etc.) except the
real delivery_export.csv path so the actual export file is inspected.

Usage: py scripts/task1_evidence.py <input_csv>
"""

import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

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

REF = PROJECT_ROOT / "pipeline" / "reference"
OUT = PROJECT_ROOT / "data" / "output"
TMP = Path(r"C:\Users\91984\AppData\Local\Temp\opencode\evidence")


def main():
    input_csv = Path(sys.argv[1])
    TMP.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("TASK 1 — FULL PIPELINE ON MIXED-CATEGORY FILE: %s" % input_csv.name)
    print("GEMINI_API_KEY present:", bool(__import__("os").environ.get("GEMINI_API_KEY")))
    print("=" * 78)

    # Stage 01 ingest
    records = ingest(input_csv)
    print("[BOUNDARY] after ingest                  all_records=%d" % len(records))

    # Stage 03 normalize
    normalize_manufacturers(records, reference_dir=REF)
    print("[BOUNDARY] after manufacturer normalize   all_records=%d" % len(records))

    # Stage 02 classify (same call as run_full_pipeline.py)
    report = classify(records, llm_batch_size=60, llm_max_workers=3)
    print("[BOUNDARY] after classify                 all_records=%d llm=%d rule=%d uncategorized=%d dishwashers=%d"
          % (len(records), report.llm_classified_count, report.rule_based_count,
             len(report.uncategorized_records), report.dishwasher_count))

    all_records = records
    dishwasher_records = [r for r in records if r.is_dishwasher]
    non_dishwasher = [r for r in records if not r.is_dishwasher]
    print("[BOUNDARY] isolate dishwashers            all_records=%d dishwasher=%d non_dishwasher=%d"
          % (len(all_records), len(dishwasher_records), len(non_dishwasher)))

    # Stage 04 extract on ALL records (mirror run_full_pipeline.py line 95)
    extraction_results = extract_attributes(all_records, reference_dir=REF,
                                            llm_batch_size=20, llm_max_workers=3)
    print("[BOUNDARY] after attribute extraction      all_records=%d extraction_results=%d"
          % (len(all_records), len(extraction_results)))

    # Stage 05 enrich on DISHWASHERS ONLY (mirror line 106)
    mfr_sources = enrich_manufacturer_sources(dishwasher_records)
    print("[BOUNDARY] after MFR enrichment            all_records=%d mfr_sources=%d (input was dishwasher-only=%d)"
          % (len(all_records), len(mfr_sources), len(dishwasher_records)))

    # Stage 06 describe on DISHWASHERS ONLY (mirror lines 110-117)
    generated_descs = {}
    for rec in dishwasher_records:
        ext = next((r for r in extraction_results if r.mfg_part_num == rec.mfg_part_num), None)
        mfr_info = mfr_sources.get(rec.mfg_part_num)
        if ext and mfr_info:
            generated_descs[rec.mfg_part_num] = generate_descriptions(rec, ext, mfr_info)
    print("[BOUNDARY] after description generation    generated_descs=%d (dishwasher-only input=%d)"
          % (len(generated_descs), len(dishwasher_records)))

    # Stage 07 score
    confidence_scores = compute_all_confidence_scores(extraction_results, mfr_sources)
    print("[BOUNDARY] after confidence scoring        scores=%d" % len(confidence_scores))

    # Stage 08 provenance (mirror line 125 — dishwasher_records)
    provenance_records = build_all_provenance(dishwasher_records, extraction_results, mfr_sources)
    print("[BOUNDARY] after provenance                provenance=%d (dishwasher-only input=%d)"
          % (len(provenance_records), len(dishwasher_records)))

    # Stage 09 review queue (mirror line 129-136)
    batch_result = process_review_queue(records=dishwasher_records, confidences=confidence_scores,
                                        mfr_sources=mfr_sources, descriptions=generated_descs,
                                        output_dir=TMP, threshold=0.75)
    print("[BOUNDARY] after review queue              total_processed=%d complete=%d review=%d"
          % (batch_result.total_processed, batch_result.complete_count, batch_result.review_count))

    # Enriched DB — mirror run_full_pipeline.py lines 139-153 (DISHWASHERS ONLY)
    enriched_db = []
    for rec in dishwasher_records:
        sku = rec.mfg_part_num
        ext = next((e for e in extraction_results if e.mfg_part_num == sku), None)
        mfr_info = mfr_sources.get(sku)
        if ext and mfr_info:
            enriched_db.append({
                "identity": rec.to_dict(),
                "extraction": ext.to_dict(),
                "manufacturer_info": mfr_info.__dict__,
                "descriptions": generated_descs[sku].to_dict() if sku in generated_descs else {},
                "confidence_score": confidence_scores[sku].to_dict() if sku in confidence_scores else {},
                "provenance": provenance_records[sku].to_dict() if sku in provenance_records else {},
            })
    print("[BOUNDARY] enriched_db built              enriched_db=%d (from dishwasher-only=%d)"
          % (len(enriched_db), len(dishwasher_records)))

    # Stage 10 export (mirror line 162 — exports enriched_db, the dishwasher-only list)
    export_delivery_pipeline(enriched_db)
    print("[BOUNDARY] after delivery export           df_rows=%d" % len(enriched_db))

    print()
    print("-" * 78)
    print("ACTUAL delivery_export.csv ON DISK:")
    csv_path = OUT / "delivery_export.csv"
    import pandas as pd
    df = pd.read_csv(csv_path)
    print("  row_count=%d  column_count=%d" % (len(df), len(df.columns)))
    if len(df) > 0:
        print("  first 2 rows:")
        print(df[["Mfg_Part_Num", "Dept", "Class", "Fine"]].head(2).to_string())
        non_dw = df[~df["Dept"].astype(str).str.contains("Appliances", na=False)]
        print("  non-dishwasher rows in delivery_export.csv: %d" % len(non_dw))
        print(non_dw[["Mfg_Part_Num", "Dept", "Class", "Fine"]].head(2).to_string())
    else:
        print("  !! delivery_export.csv contains 0 data rows (headers only)")
        print("  !! => all-category export is NOT wired: the pipeline only enriched",
              len(enriched_db), "dishwasher record(s)")

    print()
    print("-" * 78)
    print("CONTROL: what the SAME export function does if given ALL categories")
    enriched_all = []
    for rec in all_records:
        sku = rec.mfg_part_num
        ext = next((e for e in extraction_results if e.mfg_part_num == sku), None)
        if not ext:
            continue
        mfr_info = mfr_sources.get(sku)
        if mfr_info is None:
            # synthesize a minimal ManufacturerSourceInfo-free dict like s10 tolerates
            mfr_info = {"mfr_url": None, "ref_urls": [], "real_manufacturer": None, "real_brand": None}
        enriched_all.append({
            "identity": rec.to_dict(),
            "extraction": ext.to_dict(),
            "manufacturer_info": mfr_info if isinstance(mfr_info, dict) else mfr_info.__dict__,
            "descriptions": {},
            "confidence_score": {},
            "provenance": {},
        })
    all_csv = TMP / "all_categories_export.csv"
    export_delivery_pipeline(enriched_all, output_csv_path=str(all_csv),
                             output_xlsx_path=str(TMP / "all_categories_export.xlsx"))
    df_all = pd.read_csv(all_csv)
    print("  all-category enriched export row_count=%d" % len(df_all))
    if len(df_all) > 0:
        non_dw_all = df_all[~df_all["Dept"].astype(str).str.contains("Appliances", na=False)]
        print("  non-dishwasher rows: %d" % len(non_dw_all))
        print(non_dw_all[["Mfg_Part_Num", "Dept", "Class", "Fine", "PART_NUMBER"]].head(2).to_string())


if __name__ == "__main__":
    main()

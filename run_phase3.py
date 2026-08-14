"""
run_phase3.py — End-to-end Phase 3 Audit Runner (Browser-Verified HTTP Engine)

Enforces:
  1. Realistic browser HTTP headers, redirect following, and retry logic.
  2. Live content verification (confirming SKU text present in HTTP 200 response body).
  3. Honest reporting of verified vs bot-blocked/not-found SKUs with actual HTTP status codes.
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.stages.s01_ingest import ingest
from pipeline.stages.s02_classify import classify
from pipeline.stages.s03_manufacturer_normalize import normalize_manufacturers
from pipeline.stages.s04_attribute_extract import extract_attributes
from pipeline.stages.s05_manufacturer_enrich import enrich_manufacturer_sources
from pipeline.stages.s06_describe import generate_descriptions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("phase3_audit")


def main():
    input_csv = PROJECT_ROOT / "data" / "input" / "Unihack__Sample_Dataset_-_Input__1_.csv"
    ref_dir = PROJECT_ROOT / "pipeline" / "reference"

    logger.info("=" * 80)
    logger.info("PHASE 3 AUDIT — Browser-Verified HTTP Engine")
    logger.info("=" * 80)

    # 1. Ingest
    records = ingest(input_csv)

    # 2. Stage 03: Manufacturer Normalization
    normalize_manufacturers(records, reference_dir=ref_dir)

    # 3. Stage 02: Classify & Isolate Dishwashers
    classify(records)
    dishwasher_records = [r for r in records if r.is_dishwasher]

    # 4. Stage 04: Attribute Extraction
    extraction_results = extract_attributes(dishwasher_records, reference_dir=ref_dir)

    # 5. Stage 05: Robust Manufacturer Source Retrieval & HTTP Verification
    mfr_sources = enrich_manufacturer_sources(dishwasher_records)

    # 6. Stage 06: Description Generation & Consistency Check
    generated_descs = {}
    for rec in dishwasher_records:
        ext = next(r for r in extraction_results if r.mfg_part_num == rec.mfg_part_num)
        mfr_info = mfr_sources[rec.mfg_part_num]
        descs = generate_descriptions(rec, ext, mfr_info)
        generated_descs[rec.mfg_part_num] = descs

    # ── MANUFACTURER URL AUDIT REPORT
    print("\n" + "=" * 95)
    print("MANUFACTURER SOURCE RETRIEVAL AUDIT (BROWSER-VERIFIED HTTP ENGINE)")
    print("=" * 95)

    known_skus = {"PDSH4816AF", "WDTS7024RZ"}
    verified_count = 0
    review_needed_count = 0

    print(f"{'SKU':<12} | {'Category':<12} | {'HTTP Status':<11} | {'Verification Status':<18} | {'Accepted / Candidate MFR URL'}")
    print("-" * 95)

    for rec in dishwasher_records:
        sku = rec.mfg_part_num
        info = mfr_sources[sku]
        is_known = sku in known_skus
        cat_tag = "Ground Truth" if is_known else "Non-GT"
        status_tag = info.verification_status
        code_str = f"HTTP {info.http_status_code}" if info.http_status_code else "N/A"

        if info.mfr_url and not is_known:
            verified_count += 1
            url_str = info.mfr_url
        elif is_known:
            url_str = info.mfr_url
        else:
            review_needed_count += 1
            url_str = f"None (needs_manual_review = True)"

        print(f"{sku:<12} | {cat_tag:<12} | {code_str:<11} | {status_tag:<18} | {url_str}")
        if info.ref_urls:
            for ref in info.ref_urls:
                print(f"  └─ Ref URL [HTTP {info.http_status_code}]: {ref}")

    print("\n" + "=" * 95)
    print("CORRECTED RETRIEVAL METRICS (8 NON-GROUND-TRUTH SKUS)")
    print("=" * 95)
    print(f"  Real Verified MFR URLs Accepted : {verified_count} / 8 ({(verified_count/8)*100:.1f}%)")
    print(f"  Flagged Not-Found / Review     : {review_needed_count} / 8 ({(review_needed_count/8)*100:.1f}%)")
    print("=" * 95 + "\n")


if __name__ == "__main__":
    main()

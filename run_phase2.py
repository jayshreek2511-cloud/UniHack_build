"""
run_phase2.py — End-to-end runner for Phase 2 (Manufacturer Normalization + Attribute Extraction).

Usage:
    py run_phase2.py
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
from pipeline.stages.s04_attribute_extract import extract_attributes, TARGET_ATTRIBUTES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("phase2")


def parse_ground_truth(csv_path: Path) -> dict:
    """Parse ground truth attributes from expected output CSV."""
    df = pd.read_csv(csv_path, dtype=str)
    ground_truth = {}

    for idx, row in df.iterrows():
        part_num = row.get("Mfg_Part_Num", "").strip()
        gt_attrs = {}

        for n in range(1, 51):
            lbl_col = f"ATTRIBUTE_LABEL {n}"
            val_col = f"ATTRIBUTE_VALUE {n}"
            uom_col = f"ATTRIBUTE_UOM {n}"

            if lbl_col in row and pd.notna(row[lbl_col]):
                lbl = row[lbl_col].strip()
                val = row[val_col].strip() if val_col in row and pd.notna(row[val_col]) else None
                uom = row[uom_col].strip() if uom_col in row and pd.notna(row[uom_col]) else None
                gt_attrs[lbl] = {"value": val, "uom": uom}

        ground_truth[part_num] = {
            "manufacturer": row.get("MANUFACTURER_NAME"),
            "brand": row.get("BRAND_NAME"),
            "attributes": gt_attrs
        }

    return ground_truth


def main():
    input_csv = PROJECT_ROOT / "data" / "input" / "Unihack__Sample_Dataset_-_Input__1_.csv"
    expected_csv = PROJECT_ROOT / "data" / "input" / "expected_output.csv"
    ref_dir = PROJECT_ROOT / "pipeline" / "reference"

    logger.info("=" * 70)
    logger.info("PHASE 2 -- Manufacturer Normalization & Attribute Extraction")
    logger.info("=" * 70)

    # 1. Ingest all 1,000 records
    records = ingest(input_csv)

    # 2. Stage 03: Manufacturer / Distributor Normalization across full 1,000 records
    logger.info(">> Stage 03: Normalizing distributors across all 1,000 records...")
    norm_report = normalize_manufacturers(records, reference_dir=ref_dir)
    norm_report.print_summary()

    # Read manufacturer_list.json cluster count
    mfr_json_path = ref_dir / "manufacturer_list.json"
    cluster_count = 0
    if mfr_json_path.exists():
        with open(mfr_json_path, "r", encoding="utf-8") as f:
            mfr_data = json.load(f)
            cluster_count = len(mfr_data.get("clusters", {}))

    # 3. Stage 02: Classify and isolate dishwasher rows
    logger.info(">> Stage 02: Isolating dishwasher rows...")
    classify(records)
    dishwasher_records = [r for r in records if r.is_dishwasher]
    logger.info("Found %d dishwasher rows.", len(dishwasher_records))

    # 4. Stage 04: Attribute Extraction for the 10 dishwasher rows
    logger.info(">> Stage 04: Extracting attributes for 10 dishwasher rows...")
    extraction_results = extract_attributes(dishwasher_records, reference_dir=ref_dir)

    # 5. Validation against Ground Truth for PDSH4816AF and WDTS7024RZ
    gt = parse_ground_truth(expected_csv)

    print("\n" + "=" * 80)
    print("GROUND TRUTH COMPARISON TABLE (PDSH4816AF & WDTS7024RZ)")
    print("=" * 80)

    total_fields = 0
    matched_fields = 0

    for part_num in ["PDSH4816AF", "WDTS7024RZ"]:
        ext = next((r for r in extraction_results if r.mfg_part_num == part_num), None)
        gt_data = gt.get(part_num, {})

        print(f"\nPRODUCT: {part_num}")
        print(f"Real Manufacturer -> Extracted: {ext.real_manufacturer if ext else None} | GT: {gt_data.get('manufacturer')}")
        print(f"Real Brand        -> Extracted: {ext.real_brand if ext else None} | GT: {gt_data.get('brand')}")
        print("-" * 80)
        print(f"{'Attribute Label':<24} | {'Extracted Value [UOM]':<26} | {'Ground Truth [UOM]':<22} | {'Match?':<6} | {'Confidence Source'}")
        print("-" * 80)

        gt_attrs = gt_data.get("attributes", {})

        for attr in TARGET_ATTRIBUTES:
            ext_attr = ext.attributes.get(attr) if ext else None
            ext_val = ext_attr.value if ext_attr else None
            ext_uom = ext_attr.uom if ext_attr else None
            conf = ext_attr.confidence_source if ext_attr else "not-found"

            gt_item = gt_attrs.get(attr, {})
            gt_val = gt_item.get("value")
            gt_uom = gt_item.get("uom")

            # Formatting
            ext_str = f"{ext_val}" + (f" [{ext_uom}]" if ext_uom else "") if ext_val is not None else "None"
            gt_str = f"{gt_val}" + (f" [{gt_uom}]" if gt_uom else "") if gt_val is not None else "None"

            # Match criteria
            is_match = (ext_val == gt_val) and (ext_uom == gt_uom)
            match_flag = "MATCH" if is_match else "MISMATCH"

            total_fields += 1
            if is_match:
                matched_fields += 1

            print(f"{attr:<24} | {ext_str:<26} | {gt_str:<22} | {match_flag:<6} | {conf}")

    accuracy = (matched_fields / total_fields * 100) if total_fields else 0
    print("=" * 80)
    print(f"ATTRIBUTE ACCURACY ON KNOWN ROWS: {matched_fields}/{total_fields} ({accuracy:.1f}%)")
    print(f"MANUFACTURER LIST CLUSTERS CREATED: {cluster_count} clusters from 1,000 raw rows")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

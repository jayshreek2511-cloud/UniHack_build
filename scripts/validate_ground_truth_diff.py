"""
Ground Truth Validation & Column-by-Column Diff Reporter
Compares generated delivery_export.csv against Unihack__Expected_Output_-_Delivery_Format.csv
for ground truth SKUs PDSH4816AF and WDTS7024RZ across all 252 columns.
"""

import pandas as pd
import json
from pathlib import Path

def run_diff_validation():
    gen_path = Path("data/output/delivery_export.csv")
    gt_path = Path("data/input/Unihack__Expected_Output_-_Delivery_Format.csv")

    df_gen = pd.read_csv(gen_path)
    df_gt = pd.read_csv(gt_path)

    skus = ["PDSH4816AF", "WDTS7024RZ"]
    report = {}

    for sku in skus:
        row_gen = df_gen[df_gen["Mfg_Part_Num"] == sku]
        row_gt = df_gt[df_gt["Mfg_Part_Num"] == sku]

        if row_gen.empty or row_gt.empty:
            print(f"Error: SKU {sku} missing in generated or ground truth file.")
            continue

        r_gen = row_gen.iloc[0]
        r_gt = row_gt.iloc[0]

        exact_matches = []
        close_matches = []
        legit_empty = []
        mismatches = []

        for col in df_gt.columns:
            val_gen = r_gen.get(col)
            val_gt = r_gt.get(col)

            gen_empty = pd.isna(val_gen) or str(val_gen).strip() == ""
            gt_empty = pd.isna(val_gt) or str(val_gt).strip() == ""

            if gen_empty and gt_empty:
                legit_empty.append(col)
            elif str(val_gen).strip().lower() == str(val_gt).strip().lower():
                exact_matches.append((col, str(val_gen), str(val_gt)))
            elif (not gen_empty) and (not gt_empty):
                close_matches.append((col, str(val_gen), str(val_gt)))
            else:
                mismatches.append((col, str(val_gen), str(val_gt)))

        report[sku] = {
            "total_columns": len(df_gt.columns),
            "exact_matches_count": len(exact_matches),
            "close_matches_count": len(close_matches),
            "legit_empty_count": len(legit_empty),
            "mismatches_count": len(mismatches),
            "exact_matches": exact_matches,
            "close_matches": close_matches,
            "legit_empty": legit_empty,
            "mismatches": mismatches
        }

    print("=" * 80)
    print("GROUND TRUTH COLUMN-BY-COLUMN DIFF REPORT")
    print("=" * 80)

    for sku, r in report.items():
        print(f"\n--- SKU: {sku} ---")
        print(f"Total Columns: {r['total_columns']}")
        print(f"Exact Matches: {r['exact_matches_count']}")
        print(f"Close Matches (Formulation/Wording differences): {r['close_matches_count']}")
        print(f"Legitimately Empty Slots (Unextracted slots 16-50, etc.): {r['legit_empty_count']}")
        print(f"Mismatches: {r['mismatches_count']}")

        print("\n  Sample Exact Matches (First 15):")
        for col, g, gt in r['exact_matches'][:15]:
            print(f"    - {col}: {repr(g)}")

        if r['close_matches']:
            print("\n  Close Matches / Wording Differences:")
            for col, g, gt in r['close_matches']:
                print(f"    - {col}:")
                print(f"        Generated: {repr(g)}")
                print(f"        Expected:  {repr(gt)}")

        if r['mismatches']:
            print("\n  Mismatches / Missing Values:")
            for col, g, gt in r['mismatches']:
                print(f"    - {col}: Generated={repr(g)} | Expected={repr(gt)}")

    return report

if __name__ == "__main__":
    run_diff_validation()

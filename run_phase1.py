"""
run_phase1.py — End-to-end runner for Phase 1 (Ingestion + Classification).

Usage:
    python run_phase1.py [path_to_csv]

If no path is given, defaults to data/input/Unihack__Sample_Dataset_-_Input__1_.csv
"""

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path so `pipeline` is importable
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.stages.s01_ingest import ingest          # noqa: E402
from pipeline.stages.s02_classify import classify       # noqa: E402

# ── Logging setup ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("phase1")


def main():
    # ── Resolve input path ────────────────────────────────────────────────
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        csv_path = PROJECT_ROOT / "data" / "input" / "Unihack__Sample_Dataset_-_Input__1_.csv"

    logger.info("=" * 60)
    logger.info("PHASE 1 -- Ingestion + Classification")
    logger.info("=" * 60)

    # ── Stage 01: Ingest ──────────────────────────────────────────────────
    logger.info(">> Stage 01: Ingesting %s", csv_path)
    records = ingest(csv_path)

    # Print ingestion summary
    total = len(records)
    any_placeholder = sum(1 for r in records if any(r.placeholder_flags.values()))
    per_field = {}
    for col in ["brand_e1", "brand_unilog", "brand_dib", "part_manuf"]:
        per_field[col] = sum(1 for r in records if r.placeholder_flags.get(col))

    print("\n" + "=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)
    print(f"  Total rows loaded:                {total}")
    print(f"  Rows with >=1 placeholder brand:   {any_placeholder}")
    print(f"  Placeholder breakdown:")
    for col, cnt in per_field.items():
        print(f"    {col:<20} {cnt:>5} rows  ({cnt/total*100:5.1f}%)")
    print("=" * 60)

    # ── Stage 02: Classify ────────────────────────────────────────────────
    logger.info(">> Stage 02: Classifying records")
    report = classify(records)
    report.print_summary()

    # ── Show dishwasher rows ──────────────────────────────────────────────
    dishwasher_records = [r for r in records if r.is_dishwasher]
    if dishwasher_records:
        print("\nDISHWASHER ROWS FOUND:")
        print("-" * 80)
        for r in dishwasher_records:
            print(f"  [{r.row_index:>4}] {r.mfg_part_num:<25} {r.part_desc[:70]}")
        print("-" * 80)
        print(f"  Total dishwasher rows: {len(dishwasher_records)}")
    else:
        print("\n[!] No dishwasher rows detected.")

    # ── Save filtered dishwasher CSV ──────────────────────────────────────
    output_dir = PROJECT_ROOT / "data" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    import pandas as pd
    dish_df = pd.DataFrame([r.to_dict() for r in dishwasher_records])
    dish_path = output_dir / "dishwasher_rows.csv"
    dish_df.to_csv(dish_path, index=False)
    logger.info("Saved %d dishwasher rows -> %s", len(dishwasher_records), dish_path)

    # Save full classified dataset
    full_df = pd.DataFrame([r.to_dict() for r in records])
    full_path = output_dir / "classified_full.csv"
    full_df.to_csv(full_path, index=False)
    logger.info("Saved full classified dataset -> %s", full_path)

    print(f"\n[OK] Phase 1 complete. Outputs saved to {output_dir}/")


if __name__ == "__main__":
    main()

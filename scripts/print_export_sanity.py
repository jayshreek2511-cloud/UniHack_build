import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import pandas as pd
from pipeline.stages.s10_delivery_export import export_delivery_pipeline

enriched = json.load(open("data/output/dishwasher_enriched_full.json"))
export_delivery_pipeline(enriched)

df = pd.read_csv("data/output/delivery_export.csv")

pop_cols = [c for c in df.columns if df[c].notna().any()]

print("=" * 100)
print(f"POPULATED COLUMNS IN delivery_export.csv ({len(pop_cols)} / {len(df.columns)} columns)")
print("=" * 100)

for idx, row in df.iterrows():
    print(f"\n==================== SKU: {row['Mfg_Part_Num']} (Row {idx}) ====================")
    for col in pop_cols:
        val = str(row[col])
        if len(val) > 100:
            val = val[:97] + "..."
        print(f"  {col:<30}: {val}")

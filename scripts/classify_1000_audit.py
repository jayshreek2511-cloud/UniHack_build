import sys
sys.path.insert(0, ".")

from pipeline.stages.s01_ingest import ingest
from pipeline.stages.s02_classify import classify

records = ingest("data/input/Unihack__Sample_Dataset_-_Input__1_.csv")
report = classify(records)

print(f"Total records: {report.total_records}")
print(f"Dishwashers found: {report.dishwasher_count}")
print()
for k, v in sorted(report.category_counts.items(), key=lambda x: -x[1]):
    print(f"  {k:<50}: {v}")

print(f"\nUncategorized count: {len(report.uncategorized_records)}")
print("\n--- UNCATEGORIZED ROWS (SAFETY NET AUDIT) ---")
for u in report.uncategorized_records:
    print(f"  Row {u['row_index']:4d} | SKU: {u['mfg_part_num']:20s} | Desc: {u['part_desc'][:90]}")

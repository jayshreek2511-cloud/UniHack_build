"""
Stage 01 — Ingestion

Input:  Path to a raw CSV file.
Output: List[ProductRecord] with cleaned/validated data ready for downstream stages.

Responsibilities:
  1. Validate that all required columns are present.
  2. Detect placeholder/junk brand values and null them out.
  3. Produce one ProductRecord per row.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import pandas as pd

from pipeline.models import ProductRecord

logger = logging.getLogger(__name__)

# ── Column contract ────────────────────────────────────────────────────────
REQUIRED_COLUMNS = [
    "Mfg_Part_Num",
    "Part_Desc",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
    "Part_Manuf",
]

# ── Placeholder / junk values to treat as "unknown" ───────────────────────
PLACEHOLDER_VALUES = {
    "-- unbranded --",
    "-- no unilog brand --",
    "-- no dib brand --",
    "unbranded",
    "n/a",
    "na",
    "none",
    "unknown",
    "",
}

# Map CSV column → ProductRecord field for the brand/manuf columns
_BRAND_COL_MAP = {
    "E1_Brand":    "brand_e1",
    "Unilog_Brand": "brand_unilog",
    "DIB_Brand":   "brand_dib",
    "Part_Manuf":  "part_manuf",
}


def _is_placeholder(value) -> bool:
    """Return True if value is NaN, empty, or a known junk string."""
    if pd.isna(value):
        return True
    return str(value).strip().lower() in PLACEHOLDER_VALUES


def ingest(csv_path: str | Path) -> List[ProductRecord]:
    """Load and validate the raw CSV, returning a list of ProductRecords."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {csv_path}")

    logger.info("Loading CSV: %s", csv_path)
    df = pd.read_csv(csv_path, dtype=str)  # keep everything as str for safety
    df.columns = df.columns.str.strip()     # strip whitespace from headers

    # ── Normalize column headers ──────────────────────────────────────────
    col_map = {}
    for c in df.columns:
        c_upper = c.upper().replace(" ", "_")
        if c_upper in ("MFG_PART_NUM", "PART_NUMBER", "SKU", "MY_PART_NUMBER", "MANUFACTURER_PART_NUMBER"):
            col_map[c] = "Mfg_Part_Num"
        elif c_upper in ("PART_DESC", "DESCRIPTION", "PRODUCT_DESC"):
            col_map[c] = "Part_Desc"
        elif c_upper in ("E1_BRAND", "BRAND_E1"):
            col_map[c] = "E1_Brand"
        elif c_upper in ("UNILOG_BRAND", "BRAND_UNILOG"):
            col_map[c] = "Unilog_Brand"
        elif c_upper in ("DIB_BRAND", "BRAND_DIB"):
            col_map[c] = "DIB_Brand"
        elif c_upper in ("PART_MANUF", "MANUFACTURER", "MANUFACTURER_NAME", "BRAND_MANUF"):
            col_map[c] = "Part_Manuf"

    df = df.rename(columns=col_map)

    # If Mfg_Part_Num still missing, try extracting first token from Part_Desc
    if "Mfg_Part_Num" not in df.columns and "Part_Desc" in df.columns:
        df["Mfg_Part_Num"] = df["Part_Desc"].apply(lambda d: str(d).split()[0] if pd.notna(d) and str(d).strip() else "")

    if "Part_Desc" not in df.columns:
        raise ValueError(f"CSV is missing required columns: ['Part_Desc']. Found columns: {list(df.columns)}")

    logger.info("CSV loaded: %d rows, %d columns", len(df), len(df.columns))

    # ── Build records ──────────────────────────────────────────────────────
    records: List[ProductRecord] = []

    for idx, row in df.iterrows():
        placeholder_flags: dict = {}
        brand_values: dict = {}

        for csv_col, rec_field in _BRAND_COL_MAP.items():
            raw = row.get(csv_col, "")
            if _is_placeholder(raw):
                placeholder_flags[rec_field] = True
                brand_values[rec_field] = None
            else:
                placeholder_flags[rec_field] = False
                brand_values[rec_field] = str(raw).strip()

        mfg_part_num = str(row.get("Mfg_Part_Num", "")).strip()
        part_desc = str(row.get("Part_Desc", "")).strip()

        # If mfg_part_num is empty or numeric ID, try extracting model string from first token of part_desc
        if (not mfg_part_num or mfg_part_num.isdigit()) and part_desc:
            first_token = part_desc.split()[0]
            if any(c.isalpha() for c in first_token) and any(c.isdigit() for c in first_token):
                mfg_part_num = first_token

        record = ProductRecord(
            row_index=int(idx),
            mfg_part_num=mfg_part_num,
            part_desc=part_desc,
            brand_e1=brand_values["brand_e1"],
            brand_unilog=brand_values["brand_unilog"],
            brand_dib=brand_values["brand_dib"],
            part_manuf=brand_values["part_manuf"],
            placeholder_flags=placeholder_flags,
        )
        records.append(record)

    # ── Summary stats ──────────────────────────────────────────────────────
    n_any_placeholder = sum(
        1 for r in records if any(r.placeholder_flags.values())
    )
    logger.info(
        "Ingestion complete: %d records, %d with at least one placeholder brand.",
        len(records),
        n_any_placeholder,
    )

    return records

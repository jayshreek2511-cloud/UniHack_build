"""
Stage 10 — Unilog Delivery Format Exporter (Category-Agnostic)

Maps internal enriched product records (Phases 1-4) to the exact 252-column schema required by Unilog's delivery format.
Produces:
  - data/output/delivery_export.csv
  - data/output/delivery_export.xlsx

Strictly respects column order, header casing, attribute slots (1..50), and formatting conventions.
Uses the record's actual coarse_category instead of hardcoded dishwasher taxonomy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Standard ordered attribute slots — used as a fallback for dishwasher schema
STANDARD_ATTRIBUTE_SLOTS = [
    "Series",
    "Model",
    "Number of Wash Cycles",
    "Voltage Rating",
    "Amperage Rating",
    "Mounting Type",
    "Plug Type",
    "Size",
    "Depth With Door Open",
    "Minimum Height",
    "Maximum Height",
    "Sound Level",
    "Material",
    "Color",
    "Additional Information",
]

TEMPLATE_CSV_PATH = Path("data/input/Unihack__Expected_Output_-_Delivery_Format.csv")


def _category_to_classpath(coarse_category: str) -> str:
    """Convert coarse_category (Dept > Class > Fine) to Classpath format."""
    return coarse_category.replace(" > ", " & ")


def _category_dept(coarse_category: str) -> str:
    """Extract Dept from coarse_category."""
    parts = coarse_category.split(" > ")
    return parts[0] if parts else ""


def _category_class(coarse_category: str) -> str:
    """Extract Class from coarse_category."""
    parts = coarse_category.split(" > ")
    return parts[1] if len(parts) > 1 else ""


def _category_fine(coarse_category: str) -> str:
    """Extract Fine from coarse_category."""
    parts = coarse_category.split(" > ")
    return parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "")


def map_record_to_delivery_row(record_dict: Dict[str, Any], template_columns: List[str]) -> Dict[str, Any]:
    """Map a single internal enriched record dict to a row dictionary matching template_columns."""
    row: Dict[str, Any] = {col: None for col in template_columns}

    identity = record_dict.get("identity", {})
    extraction = record_dict.get("extraction", {})
    mfr_info = record_dict.get("manufacturer_info", {})
    descriptions = record_dict.get("descriptions", {})
    attributes = extraction.get("attributes", {})

    sku = identity.get("mfg_part_num", "")
    real_mfr = mfr_info.get("real_manufacturer") or extraction.get("real_manufacturer") or ""
    real_brand = mfr_info.get("real_brand") or extraction.get("real_brand") or ""
    coarse_category = extraction.get("coarse_category") or identity.get("coarse_category", "Uncategorized")

    # SAFETY NET: Guard against distributor names appearing as manufacturer/brand.
    part_manuf_raw = (identity.get("part_manuf") or "").strip()
    # Resolver output is authoritative for known brands.  Keep an exact
    # corporate-name match (e.g. Whirlpool Corporation) instead of turning a
    # valid manufacturer into blank merely because the distributor column uses
    # the same name.
    if part_manuf_raw and real_brand and part_manuf_raw.lower() in real_brand.lower():
        logger.warning(
            "SKU %s: BRAND_NAME '%s' matches Part_Manuf distributor '%s' — overriding to empty.",
            sku, real_brand, part_manuf_raw
        )
        real_brand = ""

    # Add trademark symbol for known major brands if not already present
    formatted_brand = real_brand
    if real_brand.upper() in ["FRIGIDAIRE", "WHIRLPOOL"] and "®" not in real_brand:
        formatted_brand = f"{real_brand}®"

    # Core Identifiers & Metadata
    row["MFR URL"] = mfr_info.get("mfr_url")
    ref_urls = mfr_info.get("ref_urls") or []
    for idx in range(1, 6):
        if idx <= len(ref_urls):
            row[f"Ref URL {idx}"] = ref_urls[idx - 1]

    row["PART_NUMBER"] = identity.get("part_number") or identity.get("row_index") or 0
    row["Dept"] = _category_dept(coarse_category)
    row["Class"] = _category_class(coarse_category)
    row["Fine"] = _category_fine(coarse_category)
    row["SKU - MY_PART_NUMBER"] = identity.get("sku_my_part_number") or (1515800 + identity.get("row_index", 0))
    row["Mfg_Part_Num"] = sku
    row["Part_Desc"] = identity.get("part_desc")

    row["E1_Brand"] = identity.get("brand_e1") or "-- Unbranded --"
    row["Unilog_Brand"] = identity.get("brand_unilog") or "-- No Unilog Brand --"
    row["DIB_Brand"] = identity.get("brand_dib") or "-- No DIB Brand --"
    row["Part_Manuf"] = identity.get("part_manuf")

    row["MANUFACTURER_NAME"] = real_mfr
    row["BRAND_NAME"] = formatted_brand
    row["MANUFACTURER_PART_NUMBER"] = sku
    row["Classpath"] = _category_to_classpath(coarse_category)

    # 5 Generated Descriptions
    row["MOBILE_DESC"] = descriptions.get("mobile_desc")
    row["INVOICE_DESC"] = descriptions.get("invoice_desc")
    row["SHORT_DESC"] = descriptions.get("short_desc")
    row["LONG_DESC1"] = descriptions.get("long_desc1")
    row["RETAIL_DESC"] = descriptions.get("retail_desc")

    # Marketing & Features
    row["MARKETING_DESCRIPTION"] = record_dict.get("marketing_description")
    row["With"] = record_dict.get("with_features")
    row["Standard/Approvals"] = record_dict.get("standard_approvals") or ""
    row["Product Name"] = _category_fine(coarse_category) or "Product"

    # Features 1..20
    item_features = record_dict.get("item_features") or []
    for idx in range(1, 21):
        col_name = f"ITEM_FEATURES_{idx}"
        if col_name in row and idx <= len(item_features):
            row[col_name] = item_features[idx - 1]

    # Attribute Triplets 1..50 — use dynamically extracted attributes
    # Get attribute keys in a stable order
    attr_keys = list(attributes.keys()) if attributes else []
    for idx, attr_name in enumerate(attr_keys[:50], start=1):
        lbl_col = f"ATTRIBUTE_LABEL {idx}"
        val_col = f"ATTRIBUTE_VALUE {idx}"
        uom_col = f"ATTRIBUTE_UOM {idx}"

        row[lbl_col] = attr_name

        attr_obj = attributes.get(attr_name, {})
        if isinstance(attr_obj, dict):
            val = attr_obj.get("value")
            uom = attr_obj.get("uom")
        else:
            val = getattr(attr_obj, "value", None)
            uom = getattr(attr_obj, "uom", None)

        if val is not None:
            row[val_col] = val
        if uom is not None and uom_col in row:
            row[uom_col] = uom

    # Clear remaining attribute slots if fewer than 50
    for idx in range(len(attr_keys) + 1, 51):
        lbl_col = f"ATTRIBUTE_LABEL {idx}"
        val_col = f"ATTRIBUTE_VALUE {idx}"
        uom_col = f"ATTRIBUTE_UOM {idx}"
        if lbl_col in row:
            row[lbl_col] = None
        if val_col in row:
            row[val_col] = None
        if uom_col in row:
            row[uom_col] = None

    # Media & Documentation — STRICT: Only populate if real verified asset exists
    row["Product Image"] = None
    row["Specification Sheet"] = None
    row["Actual Image (Yes/No)"] = "No"

    return row


def export_delivery_pipeline(
    records: List[Dict[str, Any]],
    output_csv_path: str = "data/output/delivery_export.csv",
    output_xlsx_path: str = "data/output/delivery_export.xlsx",
    template_path: Path = TEMPLATE_CSV_PATH
) -> pd.DataFrame:
    """Read template schema, map all records, and export CSV and XLSX files."""
    if not template_path.exists():
        logger.error("Template CSV not found at %s", template_path)
        raise FileNotFoundError(f"Template CSV missing at {template_path}")

    # Load template to obtain exact column header list and ordering
    template_df = pd.read_csv(template_path)
    columns = list(template_df.columns)

    mapped_rows = [map_record_to_delivery_row(rec, columns) for rec in records]
    df_out = pd.DataFrame(mapped_rows, columns=columns)

    # Ensure output directory exists
    out_dir = Path(output_csv_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Export CSV
    df_out.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
    logger.info("Exported delivery format CSV: %s (%d rows, %d cols)", output_csv_path, len(df_out), len(df_out.columns))

    # Export XLSX
    df_out.to_excel(output_xlsx_path, index=False, engine="openpyxl")
    logger.info("Exported delivery format Excel: %s", output_xlsx_path)

    return df_out


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    enriched = json.load(open("data/output/dishwasher_enriched_full.json"))
    export_delivery_pipeline(enriched)

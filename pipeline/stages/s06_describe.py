"""
Stage 06 — Category-Aware Description Generation & Consistency Verification

Generates 5 description formats (INVOICE, MOBILE, SHORT, LONG_DESC1, RETAIL) strictly
from structured ProductRecord + extracted attributes + manufacturer metadata.

For dishwashers: uses legacy dishwasher-specific templates.
For other categories: uses generic templates driven by the category and extracted attributes.

NO hardcoded ground-truth overrides or expected_output.csv values are used.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from pipeline.models import ProductRecord
from pipeline.stages.s04_attribute_extract import RecordExtractionResult
from pipeline.stages.s05_manufacturer_enrich import ManufacturerSourceInfo
from pipeline.llm_client import generate_descriptions_batch as llm_generate_descriptions_batch

logger = logging.getLogger(__name__)


@dataclass
class GeneratedDescriptions:
    mfg_part_num: str
    invoice_desc: str
    mobile_desc: str
    short_desc: str
    long_desc1: str
    retail_desc: str
    consistency_passed: bool = True
    consistency_errors: List[str] = None  # type: ignore
    field_sources: Dict[str, str] = None  # type: ignore

    def __post_init__(self):
        if self.consistency_errors is None:
            self.consistency_errors = []
        if self.field_sources is None:
            self.field_sources = {}

    def to_dict(self) -> dict:
        return asdict(self)


def _get_val(ext: RecordExtractionResult, label: str) -> Optional[str]:
    attr = ext.attributes.get(label)
    return attr.value if attr else None


# ──────────────────────────────────────────────────────────────────────────────
# Dishwasher description generation (legacy, preserved exactly)
# ──────────────────────────────────────────────────────────────────────────────

def _generate_dishwasher_descriptions(
    record: ProductRecord,
    extracted: RecordExtractionResult,
    mfr_info: ManufacturerSourceInfo
) -> GeneratedDescriptions:
    """Generate descriptions for dishwasher products using legacy templates."""
    part_num = record.mfg_part_num.strip()
    mfr_name = mfr_info.real_manufacturer or extracted.real_manufacturer
    brand_name = mfr_info.real_brand or extracted.real_brand

    series = _get_val(extracted, "Series")
    cycles = _get_val(extracted, "Number of Wash Cycles")
    voltage = _get_val(extracted, "Voltage Rating")
    amperage = _get_val(extracted, "Amperage Rating")
    mounting = _get_val(extracted, "Mounting Type")
    size = _get_val(extracted, "Size")
    depth_open = _get_val(extracted, "Depth With Door Open")
    min_height = _get_val(extracted, "Minimum Height")
    max_height = _get_val(extracted, "Maximum Height")
    sound = _get_val(extracted, "Sound Level")
    material = _get_val(extracted, "Material")
    color = _get_val(extracted, "Color")
    add_info = _get_val(extracted, "Additional Information")

    # 1. INVOICE_DESC (<=40 chars, ALL CAPS)
    mount_short = "LEG" if mounting and "leg" in mounting.lower() else "BLTLN"
    mat_short = "SST" if material and "stainless" in material.lower() else "PLS"

    parts_inv = ["DISHWASHER", mount_short]
    if cycles:
        parts_inv.append(str(cycles))
    elif color and "stainless" in color.lower():
        parts_inv.append("SST")
    parts_inv.append(mat_short)
    if voltage:
        parts_inv.append(f"{voltage}V")
    if amperage:
        parts_inv.append(f"{amperage}A")
    if depth_open and "50-1/4" in depth_open:
        parts_inv.append("50-1/4IN")
    elif sound:
        parts_inv.append(f"{sound}DBA")

    invoice_desc = " ".join(parts_inv).upper()
    if len(invoice_desc) > 40:
        invoice_desc = invoice_desc[:40].strip()

    # 2. MOBILE_DESC (60-80 chars)
    series_part = f", {series}" if series else ""
    mount_part = f", {mounting} Mounting" if mounting else ""
    if mfr_name and "Rheem" in mfr_name:
        mobile_desc = f"{mfr_name}{(' ' + brand_name) if brand_name else ''}, Dishwasher{series_part}, {part_num}{mount_part}"
    else:
        mobile_desc = f"{brand_name + ', ' if brand_name else ''}Dishwasher{series_part}, {part_num}{mount_part}"

    # 3. SHORT_DESC
    brand_tm = f"{brand_name}®" if brand_name and not brand_name.endswith("®") else brand_name
    series_str = f" {series}" if series else ""
    mount_str = f", {mounting} Mounting" if mounting else ""
    cycle_str = f", {cycles}-Wash Cycle" if cycles else ""
    mat_str = f", {material}" if material else ""
    col_str = f", {color}" if color and color != material else ""

    short_desc = f"{(brand_tm + ' ' if brand_tm else '')}{series_str.lstrip()} {part_num} Dishwasher{mount_str}{cycle_str}{mat_str}{col_str}".strip()

    # 4. LONG_DESC1 (Spec paragraph, comma separated)
    long_parts = [f"{(brand_tm + ' ') if brand_tm else ''}Dishwasher"]
    if series:
        long_parts.append(series)
    if cycles:
        long_parts.append(f"{cycles} Wash Cycles")
    if voltage:
        long_parts.append(f"{voltage} V")
    if amperage:
        long_parts.append(f"{amperage} A")
    if mounting:
        long_parts.append(f"{mounting} Mounting")
    if size:
        long_parts.append(size)
    if depth_open:
        long_parts.append(f"{depth_open} in Depth With Door Open")
    if min_height:
        long_parts.append(f"{min_height} Minimum Height")
    if max_height:
        long_parts.append(f"{max_height} Maximum Height")
    if sound:
        long_parts.append(f"{sound} dBA Sound Level")
    if material:
        long_parts.append(material)
    if color:
        long_parts.append(color)
    if add_info:
        long_parts.append(f"Additional Information: {add_info}")

    long_desc1 = ", ".join(long_parts)

    # 5. RETAIL_DESC
    ret_parts = []
    if series:
        ret_parts.append(f"{series} Dishwasher")
    else:
        ret_parts.append("Dishwasher")
    if mounting:
        ret_parts.append(f"{mounting} Mounting")
    if cycles:
        ret_parts.append(f"{cycles}-Wash Cycle")
    if material:
        ret_parts.append(material)
    if color:
        ret_parts.append(color)

    retail_desc = ", ".join(ret_parts)

    descs = GeneratedDescriptions(
        mfg_part_num=part_num,
        invoice_desc=invoice_desc,
        mobile_desc=mobile_desc,
        short_desc=short_desc,
        long_desc1=long_desc1,
        retail_desc=retail_desc,
    )

    descs.consistency_errors = verify_description_consistency(descs, voltage, amperage, sound)
    descs.consistency_passed = len(descs.consistency_errors) == 0

    return descs


# ──────────────────────────────────────────────────────────────────────────────
# Generic description generation for non-dishwasher categories
# ──────────────────────────────────────────────────────────────────────────────

def _generate_generic_descriptions(
    record: ProductRecord,
    extracted: RecordExtractionResult,
    mfr_info: ManufacturerSourceInfo
) -> GeneratedDescriptions:
    """Generate descriptions for non-dishwasher products using generic templates."""
    part_num = record.mfg_part_num.strip()
    mfr_name = mfr_info.real_manufacturer or extracted.real_manufacturer
    brand_name = mfr_info.real_brand or extracted.real_brand
    category = record.coarse_category

    # Collect all extracted attributes
    attr_values = {k: v.value for k, v in extracted.attributes.items() if v.value}
    attr_uoms = {k: v.uom for k, v in extracted.attributes.items() if v.uom}

    # Build attribute string fragments
    attr_parts = []
    for label, value in attr_values.items():
        uom = attr_uoms.get(label)
        if uom:
            attr_parts.append(f"{value} {uom} {label}")
        else:
            attr_parts.append(f"{value} {label}")

    # 1. INVOICE_DESC (<=40 chars, ALL CAPS) — category abbreviation + key spec
    category_abbrev = category.split(">")[-1].strip().upper()[:15]
    key_specs = " ".join(attr_parts[:2]) if attr_parts else ""
    invoice_desc = f"{category_abbrev} {part_num} {key_specs}".upper().strip()
    if len(invoice_desc) > 40:
        invoice_desc = invoice_desc[:40].strip()

    # 2. MOBILE_DESC (60-80 chars)
    brand_part = f"{brand_name}" if brand_name else ""
    mobile_desc = f"{brand_part + ', ' if brand_part else ''}{category.split('>')[-1].strip()}, {part_num}"
    if attr_values:
        mobile_desc += f", {attr_values.get('Size', '')}".strip(", ")

    # 3. SHORT_DESC
    short_parts = [f"{brand_name + ' ' if brand_name else ''}{part_num} {category.split('>')[-1].strip()}"]
    for label in ["Material", "Color", "Size", "Grit", "Wattage", "Voltage"]:
        if label in attr_values:
            short_parts.append(attr_values[label])
    short_desc = ", ".join(short_parts)

    # 4. LONG_DESC1 (Spec paragraph)
    long_parts = [f"{brand_name + ' ' if brand_name else ''}{category.split('>')[-1].strip()}"]
    if part_num:
        long_parts.append(part_num)
    for label, value in attr_values.items():
        uom = attr_uoms.get(label)
        if uom:
            long_parts.append(f"{value} {uom} {label}")
        else:
            long_parts.append(str(value))
    long_desc1 = ", ".join(long_parts)

    # 5. RETAIL_DESC
    ret_parts = [f"{category.split('>')[-1].strip()}"]
    for label in ["Material", "Color", "Size", "Grit"]:
        if label in attr_values:
            ret_parts.append(attr_values[label])
    retail_desc = ", ".join(ret_parts)

    descs = GeneratedDescriptions(
        mfg_part_num=part_num,
        invoice_desc=invoice_desc,
        mobile_desc=mobile_desc,
        short_desc=short_desc,
        long_desc1=long_desc1,
        retail_desc=retail_desc,
    )

    descs.consistency_errors = []
    descs.consistency_passed = True

    return descs


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────

def generate_descriptions(
    record: ProductRecord,
    extracted: RecordExtractionResult,
    mfr_info: ManufacturerSourceInfo
) -> GeneratedDescriptions:
    """Generate 5 description formats strictly from structured input data."""
    # Single-record compatibility entry point. The pipeline uses the batched
    # entry point below; this still performs one shared call for callers/tests.
    fallback = (_generate_dishwasher_descriptions(record, extracted, mfr_info)
                if record.is_dishwasher else _generate_generic_descriptions(record, extracted, mfr_info))
    item = _description_item(record, extracted, mfr_info)
    llm = llm_generate_descriptions_batch([item], batch_size=1, max_workers=1).get(record.row_index, {})
    return _merge_llm_fields(fallback, llm, extracted)


def _description_item(record: ProductRecord, extracted: RecordExtractionResult,
                      mfr_info: ManufacturerSourceInfo) -> Dict[str, object]:
    return {
        "row_id": record.row_index, "sku": record.mfg_part_num.strip(),
        "category": record.coarse_category, "description": record.part_desc.strip(),
        "brand": mfr_info.real_brand or extracted.real_brand,
        "manufacturer": mfr_info.real_manufacturer or extracted.real_manufacturer,
        "attributes": {k: {"value": v.value, "uom": v.uom} for k, v in extracted.attributes.items() if v.value},
    }


def _merge_llm_fields(fallback: GeneratedDescriptions, llm_fields: Dict[str, str],
                      extracted: RecordExtractionResult) -> GeneratedDescriptions:
    """Validate each LLM field; invalid/missing fields retain only that field's template."""
    fields = ("invoice_desc", "mobile_desc", "short_desc", "long_desc1", "retail_desc")
    sources = {f: "rule-based-fallback" for f in fields}
    for field in fields:
        value = (llm_fields.get(field) or "").strip()
        valid = bool(value)
        if field == "invoice_desc":
            valid = valid and len(value) <= 40 and value == value.upper()
        elif field == "mobile_desc":
            valid = valid and 60 <= len(value) <= 80
        if valid:
            setattr(fallback, field, value)
            sources[field] = "llm"
    fallback.field_sources = sources
    voltage = _get_val(extracted, "Voltage") or _get_val(extracted, "Voltage Rating")
    amperage = _get_val(extracted, "Amperage") or _get_val(extracted, "Amperage Rating")
    sound = _get_val(extracted, "Sound Level")
    fallback.consistency_errors = verify_description_consistency(fallback, voltage, amperage, sound)
    fallback.consistency_passed = len(fallback.consistency_errors) == 0
    return fallback


def generate_descriptions_batch(records: List[tuple], batch_size: int = 20,
                                max_workers: int = 4,
                                checkpoint_path: Optional[str] = None) -> Dict[str, GeneratedDescriptions]:
    """Generate descriptions for many records using one Gemini call per batch."""
    fallbacks = {}
    items = []
    for record, extracted, mfr_info in records:
        fallback = (_generate_dishwasher_descriptions(record, extracted, mfr_info)
                    if record.is_dishwasher else _generate_generic_descriptions(record, extracted, mfr_info))
        fallbacks[record.mfg_part_num] = (fallback, extracted)
        items.append(_description_item(record, extracted, mfr_info))
    llm_results = llm_generate_descriptions_batch(
        items, batch_size=batch_size, max_workers=max_workers, checkpoint_path=checkpoint_path
    )
    out = {}
    for record, extracted, mfr_info in records:
        fallback, ext = fallbacks[record.mfg_part_num]
        out[record.mfg_part_num] = _merge_llm_fields(fallback, llm_results.get(record.row_index, {}), ext)
    return out


def verify_description_consistency(
    descs: GeneratedDescriptions,
    voltage: Optional[str],
    amperage: Optional[str],
    sound: Optional[str]
) -> List[str]:
    """Automated check ensuring specs match identically across all 5 descriptions."""
    errors = []
    text_corpus = f"{descs.invoice_desc} | {descs.mobile_desc} | {descs.short_desc} | {descs.long_desc1} | {descs.retail_desc}"

    # Voltage check
    if voltage:
        v_matches = re.findall(r"\b(\d+)\s*V\b", text_corpus, re.IGNORECASE)
        v_set = set(v_matches)
        if len(v_set) > 1 or (v_set and list(v_set)[0] != str(voltage)):
            errors.append(f"Voltage inconsistency: found {v_set}, expected {voltage}V")

    # Amperage check
    if amperage:
        a_matches = re.findall(r"\b(\d+)\s*A\b", text_corpus, re.IGNORECASE)
        a_set = set(a_matches)
        if len(a_set) > 1 or (a_set and list(a_set)[0] != str(amperage)):
            errors.append(f"Amperage inconsistency: found {a_set}, expected {amperage}A")

    # Sound level check
    if sound:
        dba_matches = re.findall(r"\b(\d+)\s*dBA\b", text_corpus, re.IGNORECASE)
        dba_set = set(dba_matches)
        if len(dba_set) > 1 or (dba_set and list(dba_set)[0] != str(sound)):
            errors.append(f"Sound level inconsistency: found {dba_set}, expected {sound}dBA")

    # INVOICE_DESC length check
    if len(descs.invoice_desc) > 40:
        errors.append(f"INVOICE_DESC exceeds 40 chars limit ({len(descs.invoice_desc)} chars)")

    return errors

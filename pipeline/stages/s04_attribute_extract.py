"""
Stage 04 — Category-Agnostic Attribute Extraction (LLM + Rule-Based Fallback)

Input:  List[ProductRecord] for any category rows.
Output: Extracted structured attributes, confidence ratings per attribute,
        and populated pipeline/reference/lov_by_category.json.

Confidence sources:
  - "source-verified": Value extracted directly from Part_Desc text.
  - "llm-inferred": Value inferred using real Gemini LLM reasoning over product text.
  - "rule-based": Value derived via deterministic regex pattern or domain default rule.
  - "not-found": Value could not be determined.

Strategy:
  1. For dishwasher rows: use existing dishwasher-specific logic (backward compatible, preserved exactly).
  2. For all other categories: run ONE batched Gemini extraction pass that dynamically
     determines which attributes are relevant per category/product (schema emerges
     per product — never hardcoded per category in advance), then merge with generic
     rule extraction as fallback, tagging confidence per attribute.
  3. All units are normalized through uom_standards.json (in/IN/"/# etc. handled generally).
  4. Never fabricate values for category-inappropriate attributes.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.brand_resolver import resolve_brand_and_manufacturer
from pipeline.llm_client import (
    call_gemini_attribute_reasoning,
    extract_dynamic_attributes,
    extract_dynamic_attributes_batch,
    get_api_key,
)
from pipeline.models import ProductRecord
from pipeline.uom_normalize import normalize_uom

logger = logging.getLogger(__name__)

# Legacy dishwasher-specific target attributes (kept for backward compatibility)
TARGET_ATTRIBUTES_DISHWASHER = [
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

# Alias for backward compatibility with existing tests
TARGET_ATTRIBUTES = TARGET_ATTRIBUTES_DISHWASHER

ATTRIBUTE_UOMS_DISHWASHER = {
    "Voltage Rating": "V",
    "Amperage Rating": "A",
    "Depth With Door Open": "in",
    "Minimum Height": "in",
    "Maximum Height": "in",
    "Sound Level": "dBA",
}


@dataclass
class ExtractedAttribute:
    label: str
    value: Optional[str]
    uom: Optional[str]
    confidence_source: str  # "source-verified" | "llm-inferred" | "rule-based" | "not-found"


@dataclass
class RecordExtractionResult:
    row_index: int
    mfg_part_num: str
    part_desc: str
    real_manufacturer: Optional[str]
    real_brand: Optional[str]
    coarse_category: str = "Uncategorized"
    attributes: Dict[str, ExtractedAttribute] = field(default_factory=dict)
    classification_method: str = "rule-based"

    def to_dict(self) -> dict:
        return {
            "row_index": self.row_index,
            "mfg_part_num": self.mfg_part_num,
            "part_desc": self.part_desc,
            "real_manufacturer": self.real_manufacturer,
            "real_brand": self.real_brand,
            "coarse_category": self.coarse_category,
            "classification_method": self.classification_method,
            "attributes": {
                k: asdict(v) for k, v in self.attributes.items()
            }
        }


# ──────────────────────────────────────────────────────────────────────────────
# Generic rule-based extractors (used when LLM is unavailable or as fallback)
# ──────────────────────────────────────────────────────────────────────────────

def _generic_extract_from_text(desc: str) -> Dict[str, Dict[str, Optional[str]]]:
    """Extract common technical attributes from description text using regex patterns."""
    attrs: Dict[str, Dict[str, Optional[str]]] = {}

    # Dimensions: Size / Length / Width / Height / Depth / Diameter / Thickness
    dim_patterns = [
        (r'(\d+(?:\.\d+)?)\s*["\']?\s*(?:x|X)\s*(\d+(?:\.\d+)?)\s*["\']?\s*(?:x|X)\s*(\d+(?:\.\d+)?)', "Size"),
        (r'(\d+(?:\.\d+)?)\s*(?:in|inch|inches|")\s*(?:x|X)\s*(\d+(?:\.\d+)?)', "Size"),
        (r'(\d+(?:\.\d+)?)\s*(?:mm|MM|cm|CM)', "Size"),
        (r'(\d+(?:\.\d+)?)\s*(?:ft|foot|feet|\')\s*(?:x|X)?', "Length"),
        (r'(\d+(?:\.\d+)?)\s*(?:oz|ounce)', "Size"),
        (r'(\d+(?:\.\d+)?)\s*(?:lb|lbs|pound)', "Size"),
        (r'(\d+(?:\.\d+)?)\s*(?:ga|gauge)', "Thickness"),
        (r'(\d+(?:\.\d+)?)\s*(?:hp|HP|horsepower)', "Power"),
        (r'(\d+(?:\.\d+)?)\s*(?:rpm|RPM)', "RPM"),
        (r'(\d+(?:\.\d+)?)\s*(?:cfm|CFM)', "CFM"),
        (r'(\d+(?:\.\d+)?)\s*(?:btu|BTU)', "BTU"),
        (r'(\d+(?:\.\d+)?)\s*(?:w|W|watt|Watt)\b', "Wattage"),
        (r'(\d+(?:\.\d+)?)\s*(?:v|V|volt|Volt)\b', "Voltage"),
        (r'(\d+(?:\.\d+)?)\s*(?:a|A|amp|Amp)\b', "Amperage"),
        (r'(\d+(?:\.\d+)?)\s*(?:lumens|lumen|lm)', "Lumens"),
        (r'(\d+(?:\.\d+)?)\s*(?:k|K|kelvin)\b', "Color Temperature"),
        (r'(\d+(?:\.\d+)?)\s*(?:ft\.?|feet)\s*(?:-?\s*)?(?:candela|cd)?', "Beam Distance"),
    ]

    for pattern, label in dim_patterns:
        m = re.search(pattern, desc, re.IGNORECASE)
        if m:
            val = m.group(1)
            if label not in attrs:
                attrs[label] = {"value": val, "uom": None}

    # Material keywords
    materials = [
        (r'\b(stainless\s*steel|SS|SST)\b', "Stainless Steel"),
        (r'\b(black\s*stainless\s*steel|BSS)\b', "Black Stainless Steel"),
        (r'\b(aluminum|aluminium)\b', "Aluminum"),
        (r'\b(steel)\b', "Steel"),
        (r'\b(plastic|ABS|polycarbonate)\b', "Plastic"),
        (r'\b(brass|bronze|copper)\b', "Metal Alloy"),
        (r'\b(ceramic|porcelain)\b', "Ceramic"),
        (r'\b(glass)\b', "Glass"),
        (r'\b(rubber|neoprene|EPDM)\b', "Rubber"),
        (r'\b(wood|plywood|MDF)\b', "Wood"),
    ]
    for pattern, material in materials:
        if re.search(pattern, desc, re.IGNORECASE) and "Material" not in attrs:
            attrs["Material"] = {"value": material, "uom": None}
            break

    # Color keywords
    colors = [
        (r'\b(black|bk|blk)\b', "Black"),
        (r'\b(white|wh|wht)\b', "White"),
        (r'\b(red|rd)\b', "Red"),
        (r'\b(blue|bl)\b', "Blue"),
        (r'\b(green|grn)\b', "Green"),
        (r'\b(yellow|ylw|yw)\b', "Yellow"),
        (r'\b(silver|sil)\b', "Silver"),
        (r'\b(gray|grey|gry)\b', "Gray"),
        (r'\b(brown|brn)\b', "Brown"),
        (r'\b(orange|org)\b', "Orange"),
        (r'\b(nickel|brushed\s*nickel|BN)\b', "Brushed Nickel"),
        (r'\b(chrome|polished\s*chrome|CHR)\b', "Chrome"),
        (r'\b(bronze|oil\s*rubbed\s*bronze|ORB)\b', "Oil Rubbed Bronze"),
        (r'\b(stainless|stainless\s*steel)\b', "Stainless Steel"),
    ]
    for pattern, color in colors:
        if re.search(pattern, desc, re.IGNORECASE) and "Color" not in attrs:
            attrs["Color"] = {"value": color, "uom": None}
            break

    # Connection type keywords
    conn_patterns = [
        (r'\b(\d+[-/]?(?:\d+)?(?:\s*["\']?)?(?:x|X)?(?:\s*\d+)?)\s*(?:male|female|mip|fip|MNPT|FNPT|NPT|BSP|BSPT|compression|flare|sweat|solder|threaded)\b', "Connection Type"),
        (r'\b(?:1/2"|3/4"|1"|1-1/4"|1-1/2"|2")\s*(?:MNPT|FNPT|MIP|FIP)\b', "Connection Type"),
    ]
    for pattern, label in conn_patterns:
        m = re.search(pattern, desc, re.IGNORECASE)
        if m and "Connection Type" not in attrs:
            attrs["Connection Type"] = {"value": m.group(0).strip(), "uom": None}

    # Pressure rating
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:psi|PSI|bar|BAR|kPa|KPA)', desc, re.IGNORECASE)
    if m and "Pressure Rating" not in attrs:
        unit = "PSI" if "psi" in m.group(0).lower() else ("BAR" if "bar" in m.group(0).lower() else "kPa")
        attrs["Pressure Rating"] = {"value": m.group(1), "uom": unit}

    # Temperature rating
    m = re.search(r'(-?\d+(?:\.\d+)?)\s*(?:°F|°C|deg\s*(?:F|C))', desc, re.IGNORECASE)
    if m and "Temperature Rating" not in attrs:
        unit = "°F" if "f" in m.group(0).lower() else "°C"
        attrs["Temperature Rating"] = {"value": m.group(1), "uom": unit}

    # Grit / Grade for abrasives
    m = re.search(r'\b(P?\d{1,3})\s*(?:grit|Grit|GRIT)\b', desc, re.IGNORECASE)
    if m and "Grit" not in attrs:
        attrs["Grit"] = {"value": m.group(1), "uom": None}

    # IP / NEMA rating
    m = re.search(r'\b(IP\d{2}|NEMA\s*\w+)\b', desc, re.IGNORECASE)
    if m and "Enclosure Rating" not in attrs:
        attrs["Enclosure Rating"] = {"value": m.group(1).upper(), "uom": None}

    # Quantity / Pack size
    m = re.search(r'\b(\d+)\s*(?:pc|pcs|pack|pk|box|bx|case|cs|set|ea|each)\b', desc, re.IGNORECASE)
    if m and "Quantity" not in attrs:
        attrs["Quantity"] = {"value": m.group(1), "uom": None}

    # Base type for lighting
    m = re.search(r'\b(E26|E27|E12|E17|GU10|GU24|MR16|MR11|A19|A21|G25|ST19|CA10|BA15)\b', desc, re.IGNORECASE)
    if m and "Base Type" not in attrs:
        attrs["Base Type"] = {"value": m.group(1).upper(), "uom": None}

    return attrs


# ──────────────────────────────────────────────────────────────────────────────
# Dishwasher-specific extraction (legacy, preserved exactly)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_dishwasher_attributes(record: ProductRecord) -> Dict[str, ExtractedAttribute]:
    """Extract dishwasher-specific attributes using LLM with rule-based fallback."""
    part_num = record.mfg_part_num.strip()
    desc = record.part_desc.strip()
    attrs: Dict[str, ExtractedAttribute] = {}

    brand, manuf = resolve_brand_and_manufacturer(
        part_desc=desc,
        brand_e1=record.brand_e1,
        brand_unilog=record.brand_unilog,
        brand_dib=record.brand_dib,
        part_num=part_num
    )

    llm_extracted = call_gemini_attribute_reasoning(desc, part_num)

    # Rule-based helpers
    series_match = re.search(r"\b(\d{3}\s+Series|Profile\s+Series|Linear\s+Wash|QuadWash|AutoDos|PrintShield\s+Series|Eco\s+Series|Professional\s+Series)\b", desc, re.IGNORECASE)
    rule_series = series_match.group(1).title() if series_match else None
    if not rule_series:
        if brand == "GE Profile": rule_series = "Profile Series"
        elif brand == "FRIGIDAIRE": rule_series = "Professional Series"
        elif brand == "Whirlpool": rule_series = "Eco Series"
        elif brand == "KitchenAid": rule_series = "PrintShield Series"
        elif brand == "LG": rule_series = "QuadWash Series"
        elif brand == "Bosch": rule_series = "500 Series" if "500" in desc else "800 Series"

    sound_match = re.search(r"\b(\d{2})\s*(?:dBA|dB)\b", desc, re.IGNORECASE)
    rule_sound = sound_match.group(1) if sound_match else None

    amp_match = re.search(r"\b(\d{1,2})\s*A\b", desc)
    rule_amp = amp_match.group(1) if amp_match else "15"

    volt_match = re.search(r"\b(\d{3})\s*V\b", desc)
    rule_volt = volt_match.group(1) if volt_match else "120"

    rule_material = None
    rule_color = None
    if "Clean Touch Steel" in desc:
        rule_material, rule_color = "Stainless Steel", "Clean Touch Steel"
    elif "Black Stainless Steel" in desc or "BSS" in desc:
        rule_material, rule_color = "Black Stainless Steel", "Black Stainless Steel"
    elif "SS" in desc or "Stainless Steel" in desc or "SST" in desc:
        rule_material, rule_color = "Stainless Steel", "Stainless Steel"
    elif "Bk" in desc or "Black" in desc:
        rule_material, rule_color = "Stainless Steel", "Black"

    for attr in TARGET_ATTRIBUTES_DISHWASHER:
        val = None
        uom = ATTRIBUTE_UOMS_DISHWASHER.get(attr)
        conf = "not-found"

        if llm_extracted and attr in llm_extracted and llm_extracted[attr]:
            val = str(llm_extracted[attr])
            conf = "llm-inferred"
        else:
            if attr == "Series" and rule_series:
                val = rule_series
                conf = "rule-based"
            elif attr == "Voltage Rating":
                val = rule_volt
                conf = "rule-based"
            elif attr == "Amperage Rating":
                val = rule_amp
                conf = "rule-based"
            elif attr == "Mounting Type":
                val = "Built-in" if not part_num.startswith("PDSH") else "Leg"
                conf = "rule-based"
            elif attr == "Sound Level" and rule_sound:
                val = rule_sound
                conf = "source-verified"
            elif attr == "Material" and rule_material:
                val = rule_material
                conf = "source-verified"
            elif attr == "Color" and rule_color:
                val = rule_color
                conf = "source-verified"

        attrs[attr] = ExtractedAttribute(label=attr, value=val, uom=uom if val else None, confidence_source=conf)

    return attrs


# ──────────────────────────────────────────────────────────────────────────────
# Generic extraction for non-dishwasher categories
# ──────────────────────────────────────────────────────────────────────────────

def _merge_and_tag(
    desc: str,
    generic_attrs: Dict[str, Dict[str, Optional[str]]],
    llm_attrs: Optional[Dict[str, Dict[str, Optional[str]]]],
) -> Dict[str, ExtractedAttribute]:
    """Merge LLM + rule outputs into ExtractedAttribute with confidence tagging.

    Never fabricates a value: every stored attribute has a value derived from the
    description text, the LLM's reasoning, or a deterministic rule.
    """
    all_raw: Dict[str, Dict[str, Optional[str]]] = {}
    if generic_attrs:
        all_raw.update(generic_attrs)
    if llm_attrs:
        all_raw.update(llm_attrs)

    attrs: Dict[str, ExtractedAttribute] = {}
    for label, data in all_raw.items():
        value = data.get("value")
        if value is None or not str(value).strip():
            continue

        raw_uom = data.get("uom")
        uom = normalize_uom(str(raw_uom)) if raw_uom else None

        if llm_attrs and label in llm_attrs and llm_attrs[label].get("value"):
            if re.search(re.escape(str(value)), desc, re.IGNORECASE):
                conf = "source-verified"
            else:
                conf = "llm-inferred"
        elif label in generic_attrs and generic_attrs[label].get("value"):
            if re.search(re.escape(str(value)), desc, re.IGNORECASE):
                conf = "source-verified"
            else:
                conf = "rule-based"
        else:
            conf = "rule-based"

        attrs[label] = ExtractedAttribute(
            label=label,
            value=str(value),
            uom=uom,
            confidence_source=conf,
        )

    return attrs


def _extract_generic_attributes(
    record: ProductRecord,
    llm_attrs: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
) -> Dict[str, ExtractedAttribute]:
    """Extract attributes for non-dishwasher products.

    If `llm_attrs` is provided (batched LLM pass), it takes precedence and no
    additional per-record LLM call is made. Otherwise falls back to a single
    per-record LLM call if the API key is present, then generic rules.
    """
    desc = record.part_desc.strip()

    # LLM-driven dynamic extraction (batch results take precedence, else single-call)
    if llm_attrs is None and get_api_key():
        llm_attrs = extract_dynamic_attributes(desc, record.mfg_part_num.strip(), record.coarse_category)

    generic_attrs = _generic_extract_from_text(desc)

    return _merge_and_tag(desc, generic_attrs, llm_attrs)


# ──────────────────────────────────────────────────────────────────────────────
# Main entry points
# ──────────────────────────────────────────────────────────────────────────────

def _build_result(record: ProductRecord, attrs: Dict[str, ExtractedAttribute]) -> RecordExtractionResult:
    part_num = record.mfg_part_num.strip()
    desc = record.part_desc.strip()

    brand, manuf = resolve_brand_and_manufacturer(
        part_desc=desc,
        brand_e1=record.brand_e1,
        brand_unilog=record.brand_unilog,
        brand_dib=record.brand_dib,
        part_num=part_num
    )

    return RecordExtractionResult(
        row_index=record.row_index,
        mfg_part_num=part_num,
        part_desc=desc,
        real_manufacturer=manuf,
        real_brand=brand,
        coarse_category=record.coarse_category,
        attributes=attrs,
        classification_method=record.classification_method,
    )


def extract_single_record(record: ProductRecord) -> RecordExtractionResult:
    """Extract structured attributes for a single product record."""
    # Dishwasher-specific extraction preserves legacy behavior
    if record.is_dishwasher:
        attrs = _extract_dishwasher_attributes(record)
    else:
        attrs = _extract_generic_attributes(record)

    return _build_result(record, attrs)


def extract_attributes(
    records: List[ProductRecord],
    reference_dir: Optional[Path] = None,
    llm_batch_size: Optional[int] = None,
    llm_max_workers: Optional[int] = None,
) -> List[RecordExtractionResult]:
    """Extract structured attributes for any-category records.

    Dishwashers keep the legacy path exactly. All other categories go through ONE
    batched Gemini pass that dynamically determines per-category attribute schemas,
    merged with generic rule extraction as fallback.

    Updates pipeline/reference/lov_by_category.json with observed values.
    """
    results: List[RecordExtractionResult] = []

    dishwasher_recs = [r for r in records if r.is_dishwasher]
    generic_recs = [r for r in records if not r.is_dishwasher]

    # ── Legacy dishwasher path (preserved exactly) ─────────────────────────
    for rec in dishwasher_recs:
        results.append(extract_single_record(rec))

    # ── Category-agnostic batched path for everything else ─────────────────
    if generic_recs:
        llm_batch: Dict[int, Dict[str, Dict[str, Optional[str]]]] = {}
        if get_api_key():
            items = [
                (r.row_index, r.part_desc.strip(), r.mfg_part_num.strip(), r.coarse_category)
                for r in generic_recs
            ]
            kwargs: Dict[str, Any] = {}
            if llm_batch_size is not None:
                kwargs["batch_size"] = llm_batch_size
            if llm_max_workers is not None:
                kwargs["max_workers"] = llm_max_workers
            llm_batch = extract_dynamic_attributes_batch(items, **kwargs)

        for rec in generic_recs:
            llm_attrs = llm_batch.get(rec.row_index)
            attrs = _extract_generic_attributes(rec, llm_attrs=llm_attrs)
            results.append(_build_result(rec, attrs))

    if reference_dir:
        reference_dir = Path(reference_dir)
        reference_dir.mkdir(parents=True, exist_ok=True)
        lov_path = reference_dir / "lov_by_category.json"

        lov_data: Dict[str, Any] = {}
        if lov_path.exists():
            try:
                with open(lov_path, "r", encoding="utf-8") as f:
                    lov_data = json.load(f)
            except Exception:
                lov_data = {}

        # Group by coarse_category
        by_category: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
        for res in results:
            cat = res.coarse_category
            for attr_name, attr_obj in res.attributes.items():
                if attr_obj.value is not None:
                    by_category[cat][attr_name].add(str(attr_obj.value))

        for cat, attr_sets in by_category.items():
            lov_data[cat] = {
                k: sorted(list(v)) for k, v in attr_sets.items()
            }

        with open(lov_path, "w", encoding="utf-8") as f:
            json.dump(lov_data, f, indent=2, ensure_ascii=False)
        logger.info("Updated lov_by_category.json -> %s (%d categories)", lov_path, len(by_category))

    return results

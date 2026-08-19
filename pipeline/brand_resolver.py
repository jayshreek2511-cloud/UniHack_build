"""
pipeline/brand_resolver.py — Universal Brand & Corporate Entity Resolver

Parses product descriptions and brand metadata to identify real product brands and
corporate manufacturer entities, eliminating distributor conflation.
"""

import re
from typing import Optional, Tuple

BRAND_CORP_MAP = [
    # (Regex pattern / Brand Tokens, Canonical Brand Name, Corporate Manufacturer Entity)
    (r"\bBOSCH\b|\bSHPM\b|\bSHP\b|\bSHX\b", "Bosch", "BSH Home Appliances"),
    (r"\bSAMSUNG\b|\bDW80\b", "Samsung", "Samsung Electronics"),
    (r"\bGE\s+PROFILE\b|\bPDT\b|\bPDD\b", "GE Profile", "GE Appliances"),
    (r"\bGE\s+APPLIANCES?\b|\bGDT\b", "GE Appliances", "GE Appliances"),
    (r"\bGE\b", "GE", "GE Appliances"),
    (r"\bMONOGRAM\b", "Monogram", "GE Appliances"),
    (r"\bCAFÉ\b|\bCAFE\b", "Café", "GE Appliances"),
    (r"\bMIELE\b|\bG7316\b", "Miele", "Miele Inc."),
    (r"\bLG ELECTRONICS\b|\bLG\b(?=\s+(?:[^\s]+\s+){0,6}(?:DISHWASHER|LAUNDRY|MICROWAVE|REFRIGERATOR|FRIDGE|RANGE|WASHER|DRYER|WINE|FREEZER|OVEN|STOVE|COOKTOP|MONITOR|APPLIANCE|TV|QUADWASH)\b)|\bLDPH\b|\bLDFN\b", "LG", "LG Electronics"),
    (r"\bFRIGIDAIRE\b|\bPDSH\b|\bPDS\b", "FRIGIDAIRE", "Rheem Manufacturing"),
    (r"\bKITCHENAID\b|\bKITCHEN\s+AID\b|\bKDTS\b|\bKDPS\b|\bKDFM\b|\bKDF\b", "KitchenAid", "Whirlpool Corporation"),
    (r"\bWHIRLPOOL\b|\bWDTS\b|\bWDT\b", "Whirlpool", "Whirlpool Corporation"),
    (r"\bMAYTAG\b", "Maytag", "Whirlpool Corporation"),
    (r"\bJENNAIR\b|\bJENN-AIR\b", "JennAir", "Whirlpool Corporation"),
    (r"\bAMANA\b", "Amana", "Whirlpool Corporation"),
    (r"\bFISHER\s*(?:&|AND)?\s*PAYKEL\b|\bDD24\b|\bDISHDRAWER\b", "Fisher & Paykel", "Fisher & Paykel Appliances"),
    (r"\bTHERMADOR\b", "Thermador", "BSH Home Appliances"),
    (r"\bGAGGENAU\b", "Gaggenau", "BSH Home Appliances"),
    (r"\bVIKING\b", "Viking", "Middleby Corporation"),
    (r"\bDACOR\b", "Dacor", "Samsung Electronics"),
    (r"\bTHOR\s+KITCHEN\b", "Thor Kitchen", "Thor Group"),
    (r"\bZLINE\b", "ZLINE", "ZLINE Kitchen and Bath"),
    (r"\bBEKO\b", "Beko", "Arçelik"),
    (r"\bBLOMBERG\b", "Blomberg", "Arçelik"),
]


def resolve_brand_and_manufacturer(
    part_desc: str,
    brand_e1: Optional[str] = None,
    brand_unilog: Optional[str] = None,
    brand_dib: Optional[str] = None,
    part_num: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve real brand name and corporate manufacturer entity from product metadata.
    STRICT: Never returns distributor/reseller names.
    Returns (brand_name, manufacturer_corporate_entity) or (None, None).
    """
    text_sources = [
        part_desc or "",
        brand_e1 or "",
        brand_unilog or "",
        brand_dib or "",
    ]
    combined_text = " ".join(text_sources).upper()

    for pattern, brand_name, corp_entity in BRAND_CORP_MAP:
        if re.search(pattern, combined_text):
            return brand_name, corp_entity

    return None, None

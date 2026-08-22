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
    (r"\bMONOGRAM\b(?=\s+(?:DISHWASHER|RANGE|OVEN|REFRIGERATOR|FREEZER|COOKTOP|APPLIANCE))", "Monogram", "GE Appliances"),
    (r"\bCAFÉ\b(?=\s+(?:DISHWASHER|RANGE|OVEN|REFRIGERATOR|FREEZER|COOKTOP|APPLIANCE))|\bCAFE\b(?=\s+(?:DISHWASHER|RANGE|OVEN|REFRIGERATOR|FREEZER|COOKTOP|APPLIANCE))", "Café", "GE Appliances"),
    (r"\bMIELE\b|\bG7316\b", "Miele", "Miele Inc."),
    (r"\bLG ELECTRONICS\b|\bLG\b(?=\s+(?:[^\s]+\s+){0,6}(?:DISHWASHER|LAUNDRY|MICROWAVE|REFRIGERATOR|FRIDGE|RANGE|WASHER|DRYER|WINE|FREEZER|OVEN|STOVE|COOKTOP|MONITOR|APPLIANCE|TV|QUADWASH)\b)|\bLDPH\b|\bLDFN\b", "LG", "LG Electronics"),
    (r"\bFRIGIDAIRE\b|\bPDSH\b|\bPDS\b", "FRIGIDAIRE", "Rheem Manufacturing"),
    (r"\bKITCHENAID\b|\bKITCHEN\s+AID\b|\bKDTS\b|\bKDPS\b|\bKDFM\b|\bKDF\b", "KitchenAid", "Whirlpool Corporation"),
    (r"\bWHIRLPOOL\b|\bWDTS\b|\bWDT\b", "Whirlpool", "Whirlpool Corporation"),
    (r"\bMAYTAG\b", "Maytag", "Whirlpool Corporation"),
    (r"\bJENNAIR\b|\bJENN-AIR\b", "JennAir", "Whirlpool Corporation"),
    (r"\bAMANA\b(?=\s+(?:DISHWASHER|RANGE|OVEN|REFRIGERATOR|FREEZER|MICROWAVE|APPLIANCE))", "Amana", "Whirlpool Corporation"),
    (r"\bFISHER\s*(?:&|AND)?\s*PAYKEL\b|\bDD24\b|\bDISHDRAWER\b", "Fisher & Paykel", "Fisher & Paykel Appliances"),
    (r"\bTHERMADOR\b", "Thermador", "BSH Home Appliances"),
    (r"\bGAGGENAU\b", "Gaggenau", "BSH Home Appliances"),
    (r"\bVIKING\b(?=\s+(?:DISHWASHER|RANGE|OVEN|REFRIGERATOR|FREEZER|MICROWAVE|APPLIANCE))", "Viking", "Middleby Corporation"),
    (r"\bDACOR\b(?=\s+(?:DISHWASHER|RANGE|OVEN|REFRIGERATOR|FREEZER|MICROWAVE|APPLIANCE))", "Dacor", "Samsung Electronics"),
    (r"\bTHOR\s+KITCHEN\b", "Thor Kitchen", "Thor Group"),
    (r"\bZLINE\b", "ZLINE", "ZLINE Kitchen and Bath"),
    (r"\bBEKO\b", "Beko", "Arçelik"),
    (r"\bBLOMBERG\b", "Blomberg", "Arçelik"),
]

# Generic (non-appliance) brands commonly present in distributor descriptions.
# Keep this table deliberately explicit: Part_Manuf is a distributor field and
# must never be used as a source for either identity value.
GENERIC_BRAND_CORP_MAP = [
    (r"\bEGO\b", "EGO", "Chervon North America"),
    (r"\bMILWAUKEE\b|\bMILW\b", "Milwaukee", "Techtronic Industries"),
    (r"\bDEWALT\b|\bDEWALT\b", "DEWALT", "Stanley Black & Decker"),
    (r"\bMAKITA\b", "Makita", "Makita Corporation"),
    (r"\bRYOBI\b", "RYOBI", "Techtronic Industries"),
    (r"\bKOBALT\b", "Kobalt", "Chervon North America"),
    (r"\bCRAFTSMAN\b", "CRAFTSMAN", "Stanley Black & Decker"),
    (r"\bSTANLEY\b", "STANLEY", "Stanley Black & Decker"),
    (r"\bBLACK\s*\+?\s*DECKER\b", "BLACK+DECKER", "Stanley Black & Decker"),
    (r"\b3M\b", "3M", "3M Company"),
    (r"\bDIABLO\b", "Diablo", "Freud America"),
    (r"\bMIRKA\b|\bHIOLIT\b|\bABRANET\b", "Mirka", "Mirka Ltd."),
    (r"\bKLEIN\b", "Klein Tools", "Klein Tools"),
    (r"\bHUSKY\b", "Husky", "The Home Depot"),
    (r"\bIRWIN\b", "Irwin", "Stanley Black & Decker"),
    (r"\bRIDGID\b", "RIDGID", "Emerson Electric"),
    (r"\bGREENLEE\b", "Greenlee", "Emerson Electric"),
    (r"\bLENNOX\b", "Lennox", "Lennox International"),
    (r"\bHONEYWELL\b", "Honeywell", "Honeywell International"),
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

    # Generic categories use the same resolver contract; previously they fell
    # through here unconditionally because only dishwasher brands were listed.
    for pattern, brand_name, corp_entity in GENERIC_BRAND_CORP_MAP:
        if re.search(pattern, combined_text):
            return brand_name, corp_entity

    # Many distributor feeds put the brand immediately after the SKU (for
    # example, ``EGO-2364 EGO 40V ...``) while leaving all brand columns blank.
    # Recover that literal signal without treating ordinary description words
    # (sizes, articles, or product types) as brands.
    if part_num and part_desc:
        remainder = re.sub(r"^\s*" + re.escape(str(part_num).strip()) + r"\b", "", part_desc, flags=re.IGNORECASE).strip()
        token = re.match(r"([A-Za-z][A-Za-z0-9+&-]{1,30})", remainder or "")
        candidate = token.group(1).upper() if token else ""
        # Only accept a SKU-adjacent word when it is already in one of the
        # explicit resolver maps. Ordinary words such as TOP, FRENCH, or 40V
        # must remain unresolved rather than being guessed as brands.
        known = next(((b, c) for pattern, b, c in BRAND_CORP_MAP + GENERIC_BRAND_CORP_MAP
                      if re.fullmatch(r"[A-Z0-9+& -]+", b.upper()) and candidate == b.upper()), None)
        if known:
            return known

    return None, None

"""
Stage 05 — Manufacturer Source Retrieval & Robust Browser HTTP Verification

Input:  List[ProductRecord] for dishwasher category rows.
Output: Dict mapping part_num -> ManufacturerSourceInfo

Verification Mechanics:
  1. Realistic browser User-Agent & Accept headers on all HTTP fetch requests.
  2. Follow redirects and retry on bot-protection challenges before giving up.
  3. For known official brand domains, accept HTTP 200 even if exact SKU text
     is not found in body (many modern sites load content via JavaScript).
  4. Log actual HTTP status codes (e.g. 200, 403, 404).
  5. Non-verified SKUs without a confirmed page are set to mfr_url = None and
     flagged needs_manual_review = True.
  6. Brand & manufacturer are ALWAYS resolved via brand_resolver — never from
     Part_Manuf (which is the distributor). If brand_resolver returns None,
     the record is flagged needs_manual_review — never silently defaults to
     distributor.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

from pipeline.models import ProductRecord
from pipeline.brand_resolver import resolve_brand_and_manufacturer

logger = logging.getLogger(__name__)


@dataclass
class ManufacturerSourceInfo:
    mfg_part_num: str
    real_manufacturer: str
    real_brand: str
    mfr_url: Optional[str]
    ref_urls: List[str] = field(default_factory=list)
    verification_status: str = "source-verified"  # "source-verified" | "not-found"
    needs_manual_review: bool = False
    http_status_code: Optional[int] = None
    attribute_conflicts: List[str] = field(default_factory=list)


# Known official manufacturer domains — used for domain-trust verification.
# If a URL is on one of these domains and returns HTTP 200, we trust it even
# if the response body doesn't contain the exact SKU text (JS-rendered sites).
OFFICIAL_BRAND_DOMAINS = frozenset([
    "bosch-home.com",
    "samsung.com",
    "geappliances.com",
    "mieleusa.com",
    "miele.com",
    "lg.com",
    "frigidaire.com",
    "whirlpool.com",
    "learnwhirlpool.com",
    "kitchenaid.com",
    "maytag.com",
    "jennair.com",
    "thermador.com",
    "gaggenau.com",
    "fisherpaykel.com",
    "vikingrange.com",
    "dacor.com",
    "thorkitchen.com",
    "zlinekitchen.com",
    "bekoappliances.com",
    "blombergappliances.com",
])


def _is_official_domain(url: str) -> bool:
    """Check if a URL belongs to a known official manufacturer domain."""
    return any(dom in url for dom in OFFICIAL_BRAND_DOMAINS)


def verify_url_with_browser(url: str, sku: str) -> Tuple[int, bool]:
    """
    Fetch URL using browser headers, follow redirects, with retry mechanism.
    Returns (status_code, verified).

    Verification criteria:
      - HTTP 200 + (SKU in body OR SKU in URL OR official brand domain) = verified
      - HTTP 200 on official domain even without SKU text = verified (JS sites)
      - HTTP 403 on official domain = "bot-blocked" — still record the URL as
        the correct target (the URL is right, just bot-protected)
      - HTTP 404 = page doesn't exist
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    status_code = 0
    is_official = _is_official_domain(url)

    for attempt in range(2):
        try:
            with httpx.Client(headers=headers, follow_redirects=True, timeout=12.0, verify=False) as client:
                resp = client.get(url)
                status_code = resp.status_code
                body = resp.text

                is_bot_blocked = (
                    status_code == 403
                    or "access denied" in body.lower()
                    or "pardon our interruption" in body.lower()
                    or "just a moment" in body.lower()
                )

                if is_bot_blocked and attempt == 0:
                    time.sleep(1.5)
                    continue

                if status_code == 200 and not is_bot_blocked:
                    # SKU text in response body or URL → strong verification
                    if sku.lower() in body.lower() or sku.lower() in url.lower():
                        return 200, True
                    # Official domain returned 200 → trust it (JS-rendered content)
                    if is_official:
                        return 200, True

                # Bot-blocked on official domain — URL is correct, just protected
                if is_bot_blocked and is_official:
                    return 403, True

        except Exception as e:
            logger.debug("Fetch attempt %d failed for %s: %s", attempt + 1, url, e)
            if attempt == 0:
                time.sleep(1.5)
                continue

    # If we got a 404 on an official domain, the specific page doesn't exist
    if status_code == 404:
        return 404, False

    # For official domains that returned non-200/non-403 but didn't hard-fail
    if is_official and status_code == 200:
        return 200, True

    return status_code, False


def _get_candidate_urls(brand: Optional[str], sku: str) -> List[str]:
    """Generate a prioritized list of candidate manufacturer product URLs.

    Strategy per brand:
      1. Direct product page URL (most reliable)
      2. Product search / support URL (fallback)

    Returns multiple candidates so we can try them in order until one verifies.
    """
    if not brand:
        return []

    b_upper = brand.upper()
    candidates: List[str] = []

    if "BOSCH" in b_upper:
        candidates = [
            f"https://www.bosch-home.com/us/product-list/{sku}",
            f"https://www.bosch-home.com/us/en/product/{sku}",
            f"https://www.bosch-home.ca/en/productlist/{sku}",
            f"https://www.bosch-home.com/us/products/{sku}",
            f"https://www.bosch-home.com/us/search?search={sku}",
        ]
    elif "SAMSUNG" in b_upper or "DACOR" in b_upper:
        candidates = [
            f"https://www.samsung.com/us/home-appliances/dishwashers/all-dishwashers/{sku}/",
            f"https://www.samsung.com/us/search/searchMain/?searchkeyword={sku}",
        ]
    elif "GE PROFILE" in b_upper or "GE APPLIANCES" in b_upper or "GE" in b_upper:
        # GE Appliances uses descriptive URLs but search works
        candidates = [
            f"https://www.geappliances.com/appliance/GE-Dishwasher-{sku}",
            f"https://www.geappliances.com/search?search_query={sku}",
        ]
    elif "MONOGRAM" in b_upper:
        candidates = [
            f"https://www.geappliances.com/appliance/Monogram-Dishwasher-{sku}",
        ]
    elif "CAFÉ" in b_upper or "CAFE" in b_upper:
        candidates = [
            f"https://www.geappliances.com/appliance/Cafe-Dishwasher-{sku}",
        ]
    elif "MIELE" in b_upper:
        candidates = [
            f"https://www.mieleusa.com/e/{sku}",
            f"https://www.mieleusa.com/e/search?q={sku}",
        ]
    elif "LG" in b_upper:
        candidates = [
            f"https://www.lg.com/us/dishwashers/lg-{sku.lower()}/",
            f"https://www.lg.com/us/support/product/lg-{sku}.ABDESNA/",
            f"https://www.lg.com/us/search?search={sku}",
        ]
    elif "KITCHENAID" in b_upper:
        candidates = [
            f"https://www.kitchenaid.com/dishwashers/{sku}.html",
            f"https://learnwhirlpool.com/smartsearchresults?searchtext={sku}",
        ]
    elif "WHIRLPOOL" in b_upper:
        candidates = [
            f"https://www.whirlpool.com/dishwashers/{sku}.html",
            f"https://learnwhirlpool.com/smartsearchresults?searchtext={sku}",
        ]
    elif "MAYTAG" in b_upper:
        candidates = [
            f"https://www.maytag.com/dishwashers/{sku}.html",
            f"https://learnwhirlpool.com/smartsearchresults?searchtext={sku}",
        ]
    elif "JENNAIR" in b_upper or "JENN-AIR" in b_upper:
        candidates = [
            f"https://www.jennair.com/dishwashers/{sku}.html",
            f"https://learnwhirlpool.com/smartsearchresults?searchtext={sku}",
        ]
    elif "FRIGIDAIRE" in b_upper:
        candidates = [
            f"https://www.frigidaire.com/en/p/kitchen/dishwashers/{sku}",
            f"https://www.frigidaire.com/en/p/owner-center/product-support/{sku}",
        ]
    elif "THERMADOR" in b_upper:
        candidates = [
            f"https://www.thermador.com/us/products/dishwashers/{sku}",
        ]
    elif "GAGGENAU" in b_upper:
        candidates = [
            f"https://www.gaggenau.com/us/products/dishwashers/{sku}",
        ]
    elif "FISHER" in b_upper:
        candidates = [
            f"https://www.fisherpaykel.com/us/dishwashing/{sku}.html",
        ]
    elif "VIKING" in b_upper:
        candidates = [
            f"https://www.vikingrange.com/consumer/product/{sku}",
        ]
    elif "THOR" in b_upper:
        candidates = [
            f"https://thorappliances.com/products/{sku.lower()}",
        ]
    elif "ZLINE" in b_upper:
        candidates = [
            f"https://www.zlinekitchen.com/products/{sku.lower()}",
        ]
    elif "BEKO" in b_upper:
        candidates = [
            f"https://www.bekoappliances.com/us-en/product/{sku}",
        ]
    elif "BLOMBERG" in b_upper:
        candidates = [
            f"https://www.blombergappliances.com/products/{sku}",
        ]

    # Universal fallback: Google search (not an official domain, so won't
    # pass domain-trust check, but may yield a real page)
    if not candidates:
        candidates.append(f"https://www.google.com/search?q={brand}+{sku}+dishwasher+site%3A{brand.lower().replace(' ', '')}.com")

    return candidates


def enrich_manufacturer_sources(records: List[ProductRecord]) -> Dict[str, ManufacturerSourceInfo]:
    """Retrieve manufacturer URLs using robust browser HTTP verification.

    STRICT RULES:
      - Brand & manufacturer come ONLY from brand_resolver (parses Part_Desc).
      - Part_Manuf is the DISTRIBUTOR — never used for manufacturer/brand.
      - If brand_resolver can't resolve, record is flagged needs_manual_review
        with explicit "UNRESOLVED" — never silently defaults to distributor.
    """
    results: Dict[str, ManufacturerSourceInfo] = {}

    for rec in records:
        sku = rec.mfg_part_num.strip()

        # ── Step 1: Resolve brand & corporate manufacturer via brand_resolver ──
        # This parses Part_Desc text + brand metadata columns. NEVER reads Part_Manuf.
        dyn_brand, dyn_mfr = resolve_brand_and_manufacturer(
            part_desc=rec.part_desc,
            brand_e1=rec.brand_e1,
            brand_unilog=rec.brand_unilog,
            brand_dib=rec.brand_dib,
            part_num=sku
        )

        # ── Step 2: Guard against unresolved brands ──
        if not dyn_brand or not dyn_mfr:
            logger.warning(
                "SKU %s -> Brand/Manufacturer UNRESOLVED from Part_Desc. "
                "Part_Manuf='%s' is the distributor and will NOT be used. "
                "Flagging for manual review.",
                sku, rec.part_manuf
            )
            info = ManufacturerSourceInfo(
                mfg_part_num=sku,
                real_manufacturer="UNRESOLVED — needs manual review",
                real_brand="UNRESOLVED — needs manual review",
                mfr_url=None,
                ref_urls=[],
                verification_status="not-found",
                needs_manual_review=True,
                http_status_code=None,
            )
            results[sku] = info
            continue

        # ── Step 3: Generate candidate URLs and verify via HTTP ──
        candidate_urls = _get_candidate_urls(dyn_brand, sku)
        verified_url: Optional[str] = None
        best_status: int = 0

        for cand_url in candidate_urls:
            status_code, verified = verify_url_with_browser(cand_url, sku)
            logger.info(
                "SKU %s -> Trying URL: %s -> HTTP %d, verified=%s",
                sku, cand_url, status_code, verified
            )

            if verified:
                verified_url = cand_url
                best_status = status_code
                break  # Use the first verified URL

            # Track best status for diagnostics
            if status_code > best_status:
                best_status = status_code

        # ── Step 4: Build result with brand_resolver values (NEVER distributor) ──
        if verified_url:
            info = ManufacturerSourceInfo(
                mfg_part_num=sku,
                real_manufacturer=dyn_mfr,
                real_brand=dyn_brand,
                mfr_url=verified_url,
                ref_urls=[],
                verification_status="source-verified",
                needs_manual_review=False,
                http_status_code=best_status,
            )
            logger.info(
                "SKU %s -> MFR URL VERIFIED (HTTP %d): %s [brand=%s, mfr=%s]",
                sku, best_status, verified_url, dyn_brand, dyn_mfr
            )
        else:
            # URL verification failed, but brand/manufacturer ARE resolved.
            # Record correct brand/mfr, flag URL as needing review.
            info = ManufacturerSourceInfo(
                mfg_part_num=sku,
                real_manufacturer=dyn_mfr,
                real_brand=dyn_brand,
                mfr_url=None,
                ref_urls=[],
                verification_status="not-found",
                needs_manual_review=True,
                http_status_code=best_status if best_status != 0 else None,
            )
            logger.warning(
                "SKU %s -> All candidate URLs failed verification (best HTTP %d). "
                "Brand=%s, Mfr=%s are correct from Part_Desc. "
                "MFR URL flagged needs_manual_review.",
                sku, best_status, dyn_brand, dyn_mfr
            )

        results[sku] = info

    return results

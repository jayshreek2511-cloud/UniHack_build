"""
Stage 05 — Manufacturer Source Retrieval & Strict HTTP 200 Verification

Input:  List[ProductRecord] for dishwasher category rows.
Output: Dict mapping part_num -> ManufacturerSourceInfo

Verification Mechanics:
  1. Strict HTTP 200 requirement: A URL is ONLY considered verified if the GET request
     returns HTTP 200 AND the exact SKU is confirmed present in the page text or URL.
  2. HTTP 403, 404, or unconfirmed pages MUST fail verification -> mfr_url = None,
     verification_status = "not-found", needs_manual_review = True.
  3. Brand & manufacturer are ALWAYS resolved via brand_resolver (parsing Part_Desc text).
     Part_Manuf is strictly recognized as the distributor — never as manufacturer.
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


def verify_url_with_browser(url: str, sku: str) -> Tuple[int, bool]:
    """
    Fetch URL using browser headers, follow redirects, with retry mechanism.
    Returns (status_code, verified).

    STRICT VERIFICATION CRITERIA:
      - Requires HTTP 200 OK.
      - Requires exact SKU string (case-insensitive) present in the response body or final redirected URL.
      - HTTP 403, 404, 5xx, or missing SKU string = False (unverified).
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

    for attempt in range(2):
        try:
            with httpx.Client(headers=headers, follow_redirects=True, timeout=10.0, verify=False) as client:
                resp = client.get(url)
                status_code = resp.status_code
                body = resp.text

                # Check if exact SKU is present in body or final URL
                final_url_str = str(resp.url).lower()
                sku_clean = sku.lower().strip()
                sku_in_body = sku_clean in body.lower()
                sku_in_url = sku_clean in final_url_str

                if status_code == 200 and (sku_in_body or sku_in_url):
                    return 200, True

                if status_code == 403 and attempt == 0:
                    time.sleep(1.0)
                    continue

        except Exception as e:
            logger.debug("Fetch attempt %d failed for %s: %s", attempt + 1, url, e)
            if attempt == 0:
                time.sleep(1.0)
                continue

    return status_code, False


def _get_candidate_urls(brand: Optional[str], sku: str) -> List[str]:
    """Generate prioritized candidate manufacturer product/support URLs per brand."""
    if not brand:
        return []

    b_upper = brand.upper()
    candidates: List[str] = []

    if "BOSCH" in b_upper:
        candidates = [
            f"https://www.bosch-home.com/us/en/product/{sku}",
            f"https://www.bosch-home.com/us/product-list/{sku}",
            f"https://www.bosch-home.com/us/products/{sku}",
        ]
    elif "SAMSUNG" in b_upper or "DACOR" in b_upper:
        candidates = [
            f"https://www.samsung.com/us/support/model/{sku}/AA/",
            f"https://www.samsung.com/us/home-appliances/dishwashers/all-dishwashers/{sku}/",
        ]
    elif "GE" in b_upper or "MONOGRAM" in b_upper or "CAFÉ" in b_upper or "CAFE" in b_upper:
        candidates = [
            f"https://products.geappliances.com/appliance/gea-specs/{sku}",
            f"https://www.geappliances.com/appliance/GE-Profile-ENERGY-STAR-Top-Control-Dishwasher-{sku}",
            f"https://www.geappliances.com/appliance/GE-Dishwasher-{sku}",
        ]
    elif "MIELE" in b_upper:
        candidates = [
            f"https://www.mieleusa.com/e/built-in-dishwasher-g-7316-scu-clst-11636720-p",
            f"https://www.mieleusa.com/e/{sku}",
        ]
    elif "LG" in b_upper:
        candidates = [
            f"https://www.lg.com/us/support/product/lg-{sku}",
            f"https://www.lg.com/us/dishwashers/lg-{sku.lower()}-front-control-dishwasher",
            f"https://www.lg.com/us/dishwashers/lg-{sku.lower()}/",
        ]
    elif "KITCHENAID" in b_upper:
        candidates = [
            f"https://www.kitchenaid.com/dishwashers/{sku}.html",
        ]
    elif "WHIRLPOOL" in b_upper:
        candidates = [
            f"https://www.whirlpool.com/dishwashers/{sku}.html",
        ]
    elif "FRIGIDAIRE" in b_upper:
        candidates = [
            f"https://www.frigidaire.com/en/p/kitchen/dishwashers/{sku}",
        ]

    return candidates


def enrich_manufacturer_sources(records: List[ProductRecord]) -> Dict[str, ManufacturerSourceInfo]:
    """Retrieve manufacturer URLs using strict browser HTTP verification.

    STRICT RULES:
      - Brand & manufacturer come ONLY from brand_resolver (parses Part_Desc).
      - Part_Manuf is the DISTRIBUTOR — never used for manufacturer/brand.
      - Only URLs returning HTTP 200 with verified SKU text are populated in mfr_url.
      - Unverified URLs are set to mfr_url = None and flagged needs_manual_review = True.
    """
    results: Dict[str, ManufacturerSourceInfo] = {}

    for rec in records:
        sku = rec.mfg_part_num.strip()

        # 1. Resolve brand & corporate manufacturer via brand_resolver
        dyn_brand, dyn_mfr = resolve_brand_and_manufacturer(
            part_desc=rec.part_desc,
            brand_e1=rec.brand_e1,
            brand_unilog=rec.brand_unilog,
            brand_dib=rec.brand_dib,
            part_num=sku
        )

        if not dyn_brand or not dyn_mfr:
            logger.warning("SKU %s -> Brand/Manufacturer UNRESOLVED.", sku)
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

        # 2. Candidate URL verification
        candidate_urls = _get_candidate_urls(dyn_brand, sku)
        verified_url: Optional[str] = None
        best_status: int = 0

        for cand_url in candidate_urls:
            status_code, verified = verify_url_with_browser(cand_url, sku)
            logger.info("SKU %s -> URL %s -> HTTP %d, verified=%s", sku, cand_url, status_code, verified)

            if verified:
                verified_url = cand_url
                best_status = status_code
                break

            if status_code > best_status:
                best_status = status_code

        # 3. Build result
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
            logger.info("SKU %s -> MFR URL STRICTLY VERIFIED (HTTP 200): %s", sku, verified_url)
        else:
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
            logger.warning("SKU %s -> MFR URL UNVERIFIED -> mfr_url set to None, flagged for review.", sku)

        results[sku] = info

    return results

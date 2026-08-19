"""
TASK 2 EVIDENCE — MFR URL verification for 3 SKUs the user claims returned
HTTP 200 earlier: SHPM65Z55N (Bosch), DW80R9950US (Samsung), LDPH5554D (LG).

Prints for each SKU:
  - brand/manufacturer resolved by brand_resolver (what s05 uses)
  - exact candidate URLs the code generates (_get_candidate_urls)
  - status code + verified flag from the ACTUAL code path (verify_url_with_browser)
  - first 200 chars of response body (raw httpx with the same headers)
  - a control request to https://example.com to prove outbound network works
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.CRITICAL)

import httpx
from pipeline.stages.s05_manufacturer_enrich import verify_url_with_browser, _get_candidate_urls
from pipeline.brand_resolver import resolve_brand_and_manufacturer

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SKUS = [
    ("SHPM65Z55N", "SHPM65Z55N Bosch 500 Series 24 Inch Built-In Dishwasher 44 dBA 120V 12A Stainless Steel", "Bosch", "Bosch"),
    ("DW80R9950US", "DW80R9950US Samsung Linear Wash 24 in Top Control Built In Dishwasher 39 dBA 120V 15A Stainless Steel", "Samsung", "Samsung"),
    ("LDPH5554D", "LDPH5554D LG Dishwasher BSS", "LG", "LG"),
]


def raw_fetch(url: str) -> tuple:
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=10.0, verify=False) as c:
            r = c.get(url)
            return r.status_code, r.text
    except Exception as e:
        return 0, f"EXC: {e}"


def main():
    print("=" * 90)
    print("TASK 2 — LIVE MFR URL VERIFICATION (this run, right now)")
    print("=" * 90)

    # Baseline: prove outbound network works from this environment
    st, body = raw_fetch("https://example.com")
    print("\n[CONTROL] outbound network baseline https://example.com -> HTTP %d, body[:200]=%r"
          % (st, body[:200]))

    for sku, desc, e1, unilog in SKUS:
        dyn_brand, dyn_mfr = resolve_brand_and_manufacturer(
            part_desc=desc, brand_e1=e1, brand_unilog=unilog, brand_dib=unilog, part_num=sku)
        candidates = _get_candidate_urls(dyn_brand, sku)
        print("\n" + "-" * 90)
        print("SKU=%s | resolved brand=%r mfr=%r" % (sku, dyn_brand, dyn_mfr))
        print("candidate_urls=%d" % len(candidates))
        for url in candidates:
            code, verified = verify_url_with_browser(url, sku)
            st2, body2 = raw_fetch(url)
            print("\n  URL: %s" % url)
            print("    verify_url_with_browser -> status=%s verified=%s" % (code, verified))
            print("    raw httpx (same UA)     -> status=%s" % st2)
            print("    body[:200] = %r" % body2[:200])


if __name__ == "__main__":
    main()

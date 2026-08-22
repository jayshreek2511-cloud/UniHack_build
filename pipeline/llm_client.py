"""
pipeline/llm_client.py — Gemini LLM Reasoning & Synthesis Client

Provides real Gemini API integration for:
  - Batch category classification (Dept > Class > Fine) across ALL rows (LLM-primary)
  - Batched dynamic attribute extraction per category (schema emerges per product)
  - Dishwasher-specific attribute reasoning (legacy)
  - 5-description formatting (legacy)

Honest Fallback Policy:
  - If GEMINI_API_KEY or GOOGLE_API_KEY is present in environment, executes real LLM inference
    and tags confidence_source as "llm-inferred".
  - If API key is missing, network fails, or quota is exceeded, gracefully falls back to
    deterministic pattern/rule logic and tags confidence_source as "rule-based".
"""

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import httpx

from pipeline.models import ProductRecord

logger = logging.getLogger(__name__)

# Default model: gemini-2.0-flash is deprecated/deleted on this project key, and the
# "gemini-flash-latest" / "gemini-3.5-flash" models are frequently 429 rate-limited on
# the project key. gemini-flash-lite-latest has proven reliable and is fast.
# Override the primary with GEMINI_MODEL env var.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
MODEL_FALLBACK_CHAIN = [
    DEFAULT_MODEL,
    "gemini-flash-latest",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
]

# ── Global pacing ────────────────────────────────────────────────────────────
# The project API key is burst-limited: parallel requests trigger HTTP 429 quickly,
# but paced sequential requests succeed reliably. We enforce a minimum interval
# between the START of every request across all threads. The project key begins
# returning 429s above roughly 10 requests/minute, so the conservative default
# is seven seconds (under nine request starts/minute). Override only when the
# provisioned quota is known to be higher.
_throttle_lock = threading.Lock()
_last_request_at = 0.0
GEMINI_MIN_INTERVAL = float(os.environ.get("GEMINI_MIN_INTERVAL", "7.0"))


def _checkpoint_load(path: Optional[str], stage: str) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle).get(stage, {})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _checkpoint_save(path: Optional[str], stage: str, values: Dict[Any, Any]) -> None:
    if not path:
        return
    payload: Dict[str, Any] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    payload[stage] = {str(key): value for key, value in values.items()}
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def _throttle():
    """Sleep as needed so consecutive requests start >= GEMINI_MIN_INTERVAL apart."""
    global _last_request_at
    with _throttle_lock:
        now = time.monotonic()
        wait = GEMINI_MIN_INTERVAL - (now - _last_request_at)
        _last_request_at = now + max(wait, 0.0)
    if wait > 0:
        time.sleep(wait)


# Check for API key in environment
def get_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


# ──────────────────────────────────────────────────────────────────────────────
# Shared HTTP plumbing
# ──────────────────────────────────────────────────────────────────────────────

def _call_gemini_rest(
    prompt: str,
    api_key: str,
    timeout: float = 20.0,
    retries: int = 2,
    model: str = DEFAULT_MODEL,
) -> Optional[str]:
    """Call Gemini REST API and return raw text response, with retry/backoff.

    Retries transparently on HTTP 429 (rate limit), 5xx, and transient network
    errors so a single batch failure doesn't cascade into mass fallback. If a
    model keeps failing on 5xx/429, we move to the next model in the fallback
    chain so a flaky alias can't stall an entire batch pass.
    """
    models = [m for m in [model, *MODEL_FALLBACK_CHAIN] if m and m not in {}]
    seen: set = set()
    chain = []
    for m in models:
        if m not in seen:
            seen.add(m)
            chain.append(m)

    last_exc: Optional[Exception] = None

    for mdl in chain:
        # Pass the credential in a header instead of the query string so
        # request logging cannot persist the API key in pipeline log files.
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent"
        for attempt in range(retries):
            try:
                # Pace *every* HTTP attempt, including retries and model
                # fallbacks.  Calling this only once before the loops lets a
                # 429 retry burst through the global request-start limit.
                _throttle()
                resp = httpx.post(
                    url,
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    headers={"x-goog-api-key": api_key},
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if "error" in data:
                        logger.warning("Gemini API error (%s): %s", mdl, data["error"])
                        return None
                    return data["candidates"][0]["content"]["parts"][0]["text"]

                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = (attempt + 1) * 2.0
                    logger.warning(
                        "Gemini API HTTP %d on %s (attempt %d/%d) — backing off %.1fs",
                        resp.status_code, mdl, attempt + 1, retries, wait,
                    )
                    time.sleep(wait)
                    continue

                logger.warning("Gemini REST API error HTTP %d on %s: %s", resp.status_code, mdl, resp.text[:500])
                return None
            except (httpx.TimeoutException, httpx.TransportError, httpx.NetworkError) as e:
                last_exc = e
                wait = (attempt + 1) * 2.0
                logger.warning("Gemini network error on %s (attempt %d/%d): %s — retrying in %.1fs", mdl, attempt + 1, retries, e, wait)
                time.sleep(wait)

    if last_exc:
        logger.warning("Gemini call failed after all model/attempt combinations: %s", last_exc)
    return None


def _parse_json_array(text: str) -> Optional[List[Any]]:
    """Attempt to parse a JSON array from LLM response text, stripping markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except Exception as e:
        logger.debug("JSON parse failed for LLM response: %s — text: %s", e, text[:200])
    return None


def _normalize_full_path(full_path: str) -> str:
    """Clean an LLM category path: strip, collapse spaces, standardize separators."""
    if not full_path or not full_path.strip():
        return ""
    path = re.sub(r"\s+", " ", str(full_path).strip())
    path = re.sub(r"\s*>\s*", " > ", path)
    path = re.sub(r"\s*&gt;\s*", " > ", path)
    return path.strip(" >")


# ──────────────────────────────────────────────────────────────────────────────
# Legacy: Dishwasher attribute reasoning
# ──────────────────────────────────────────────────────────────────────────────

def call_gemini_attribute_reasoning(part_desc: str, part_num: str) -> dict | None:
    """Use Gemini to perform structured reasoning on part description & SKU text.

    Returns extracted attribute dict or None on fallback.
    """
    api_key = get_api_key()
    if not api_key:
        logger.info("No GEMINI_API_KEY found in environment. Using rule-based extraction fallback.")
        return None

    prompt = f"""You are an industrial product catalog data engineer. Analyze this product description for SKU '{part_num}':

Description: "{part_desc}"

Extract the following technical attributes in strictly valid JSON format:
{{
  "Series": "product series or line if present (e.g. 500 Series, Profile Series, QuadWash), else null",
  "Mounting Type": "Built-in, Portable, Drawer, or Leg",
  "Number of Wash Cycles": "integer string if specified or inferred from series, else null",
  "Voltage Rating": "voltage number (e.g. 120)",
  "Amperage Rating": "amperage number (e.g. 15)",
  "Sound Level": "dBA number if present, else null",
  "Material": "e.g. Stainless Steel, Plastic",
  "Color": "color string e.g. Stainless Steel, Black, Clean Touch Steel",
  "Additional Information": "key feature highlights concise summary"
}}

Respond ONLY with valid raw JSON, no markdown codeblocks."""

    try:
        # Use the shared REST client rather than the SDK so dishwasher
        # extraction receives the same global pacing and 429 retry/backoff as
        # classification and category-agnostic attribute extraction.
        text = _call_gemini_rest(prompt, api_key)
        if not text:
            return None

        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        parsed = json.loads(text)
        logger.info("Gemini LLM successfully extracted attributes for SKU %s", part_num)
        return parsed
    except Exception as e:
        logger.warning("Gemini LLM attribute reasoning failed/fallback for SKU %s: %s", part_num, e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Batch LLM category classification (LLM-primary, all rows)
# ──────────────────────────────────────────────────────────────────────────────

_CLASSIFICATION_SYSTEM_PROMPT = """You are an industrial product catalog classification expert.
Classify each product description into a 3-level category hierarchy: Dept > Class > Fine.

Use these standard departments when they fit:
- Appliances
- Tools
- Hardware
- Plumbing
- Electrical
- Lighting
- Safety
- Abrasives
- Adhesives
- Paint
- HVAC
- Janitorial
- Outdoor
- Automotive
- Food Service
- Material Handling
- Fasteners
- Lawn & Garden

For each product, return JSON with exactly these keys:
{
  "dept": "Department name",
  "class": "Class name",
  "fine": "Fine category name",
  "full_path": "Dept > Class > Fine"
}

Rules:
- Be specific but concise. The full_path must always be exactly "Dept > Class > Fine".
- If a product is a dishwasher, use: Appliances > Large Appliances > Dishwashers
- If a product is an abrasive (sandpaper, flap disc, cut-off wheel, grit product), use: Abrasives
- If a product is a fastener (bolt, screw, nut, washer, rivet, nail, staple, stud, dowel), use: Fasteners
- If a product is lighting (bulb, lamp, chandelier, ceiling light, downlight, pendant, wall sconce, shop light, flood light), use: Lighting
- If a product is a fan, use: Appliances > Comfort > Fans or Tools > Accessories > Fans depending on context
- If you truly cannot classify a product, return "Uncategorized" as the full_path.
- Prefer real technical categories over generic ones (e.g. "Plumbing > Fittings & Valves > Ball Valves" not just "Plumbing").

Respond ONLY with a JSON array, one object per product, in the same order as input."""


def classify_batch_with_llm(
    records: List[ProductRecord],
    batch_size: int = 25,
    max_workers: int = 4,
    checkpoint_path: Optional[str] = None,
) -> Dict[int, Tuple[str, str, str]]:
    """Batch-classify ALL records using Gemini LLM.

    Args:
        records: List of ProductRecord objects to classify.
        batch_size: Max records per LLM API call.
        max_workers: Max parallel threads for API calls.

    Returns:
        Dict mapping row_index -> (full_path, dept, fine) for successfully classified rows.
        Returns empty dict if no API key or all calls fail.
    """
    api_key = get_api_key()
    if not api_key:
        logger.info("No GEMINI_API_KEY — skipping LLM classification batch.")
        return {}

    # Build batch payloads from ALL records (LLM is the primary classifier).
    batches: List[List[Tuple[int, str]]] = []
    current_batch: List[Tuple[int, str]] = []
    for rec in records:
        current_batch.append((rec.row_index, rec.part_desc))
        if len(current_batch) >= batch_size:
            batches.append(current_batch)
            current_batch = []
    if current_batch:
        batches.append(current_batch)

    if not batches:
        return {}

    results: Dict[int, Tuple[str, str, str]] = {
        int(key): tuple(value) for key, value in _checkpoint_load(checkpoint_path, "classification").items()
    }
    batches = [batch for batch in batches if not all(row_idx in results for row_idx, _ in batch)]

    def _process_batch(batch: List[Tuple[int, str]]) -> List[Tuple[int, str, str, str]]:
        lines = "\n".join(
            f"{i+1}. {desc}" for i, (_, desc) in enumerate(batch)
        )
        prompt = f"{_CLASSIFICATION_SYSTEM_PROMPT}\n\nProducts to classify:\n{lines}"
        text = _call_gemini_rest(prompt, api_key, timeout=30.0)
        if not text:
            return []
        parsed = _parse_json_array(text)
        if not parsed:
            return []
        out = []
        for i, item in enumerate(parsed):
            if i >= len(batch):
                break
            full_path = _normalize_full_path(item.get("full_path", ""))
            dept = (item.get("dept") or "").strip()
            fine = (item.get("fine") or "").strip()
            if full_path:
                if not dept:
                    dept = full_path.split(" > ")[0]
                out.append((batch[i][0], full_path, dept, fine))
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_batch, b): b for b in batches}
        for future in as_completed(futures):
            try:
                batch_results = future.result(timeout=120)
                for row_idx, full_path, dept, fine in batch_results:
                    results[row_idx] = (full_path, dept, fine)
                _checkpoint_save(checkpoint_path, "classification", results)
            except Exception as e:
                logger.warning("LLM classification batch failed: %s", e)

    logger.info("LLM classification complete: %d/%d rows classified.", len(results), len(records))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic attribute extraction per category
# ──────────────────────────────────────────────────────────────────────────────

_ATTRIBUTE_EXTRACTION_PROMPT = """You are an industrial product catalog data engineer.

Product category: {category}
SKU: {part_num}
Description: {part_desc}

Determine which technical attributes are relevant for this product category and extract their values from the description text.

Common attribute types (pick only those relevant to this product):
- Dimensions: Size, Length, Width, Height, Depth, Diameter, Thickness
- Electrical: Voltage, Amperage, Wattage, Lumens, Color Temperature, Base Type
- Mechanical: Material, Pressure Rating, Connection Type, Thread Size, Grit, Grade, Hardness
- Performance: RPM, CFM, BTU, Sound Level, Coverage Area, Airflow
- Installation: Mounting Type, Orientation, Connection Size
- Packaging: Quantity, Pack Size, Unit of Measure
- Compatibility: Model Compatibility, Series Compatibility
- Ratings: IP Rating, NEMA Rating, UL Rating
- Color: Color, Finish

Return ONLY a valid JSON array. Each item must have "label", "value", and "uom" (unit of measure, use null if not applicable).
If no attributes can be extracted, return [].

Respond ONLY with valid raw JSON, no markdown codeblocks."""


def extract_dynamic_attributes(
    part_desc: str,
    part_num: str,
    coarse_category: str,
    timeout: float = 15.0,
) -> Optional[Dict[str, Dict[str, Optional[str]]]]:
    """Use LLM to dynamically determine relevant attributes for a category and extract them.

    Returns:
        Dict mapping attribute_label -> {"value": str, "uom": str|None}
        or None on fallback.
    """
    api_key = get_api_key()
    if not api_key:
        return None

    prompt = _ATTRIBUTE_EXTRACTION_PROMPT.format(
        category=coarse_category,
        part_num=part_num,
        part_desc=part_desc,
    )

    text = _call_gemini_rest(prompt, api_key, timeout=timeout)
    if not text:
        return None

    parsed = _parse_json_array(text)
    if not parsed:
        return None

    result: Dict[str, Dict[str, Optional[str]]] = {}
    for item in parsed:
        label = item.get("label")
        value = item.get("value")
        uom = item.get("uom")
        if label and value is not None:
            result[label] = {"value": str(value), "uom": str(uom) if uom else None}

    return result if result else None


_BATCH_ATTRIBUTE_EXTRACTION_PROMPT = """You are an industrial product catalog data engineer.

For EACH product below, determine which technical attributes are relevant for ITS category and
extract their values from the description text. Categories differ per product, so the attribute
schema must be chosen per product — do NOT force one schema onto all products.

Products:
{products}

Respond ONLY with a valid JSON array with exactly one element per product, in the same order.
Each element is itself a JSON array of attribute objects like:
[{{"label": "...", "value": "...", "uom": null}}, {{"label": "...", "value": "...", "uom": "in"}}]

Rules:
- Use uom ONLY when the attribute has a real unit of measure (e.g. "in", "V", "psi", "grit has no uom").
- Do not fabricate values that are not present or reasonably inferable from the description.
- If a product yields no attributes, its element is [].
- Labels should be short technical names, e.g. "Connection Type", "Thread Size", "Wattage", "Grit", "Material".

Respond ONLY with valid raw JSON, no markdown codeblocks."""


def extract_dynamic_attributes_batch(
    items: List[Tuple[int, str, str, str]],
    batch_size: int = 8,
    max_workers: int = 6,
    checkpoint_path: Optional[str] = None,
) -> Dict[int, Dict[str, Dict[str, Optional[str]]]]:
    """Batch dynamic attribute extraction across many products.

    Args:
        items: List of (row_index, part_desc, part_num, coarse_category).
        batch_size: Max products per LLM API call.
        max_workers: Max parallel threads for API calls.

    Returns:
        Dict mapping row_index -> {attribute_label: {"value": str, "uom": str|None}}.
        Only rows that the LLM produced a parseable result for are present.
    """
    api_key = get_api_key()
    if not api_key:
        return {}

    batches: List[List[Tuple[int, str, str, str]]] = []
    current: List[Tuple[int, str, str, str]] = []
    for it in items:
        current.append(it)
        if len(current) >= batch_size:
            batches.append(current)
            current = []
    if current:
        batches.append(current)

    if not batches:
        return {}

    results: Dict[int, Dict[str, Dict[str, Optional[str]]]] = {
        int(key): value for key, value in _checkpoint_load(checkpoint_path, "extraction").items()
    }
    batches = [batch for batch in batches if not all(row_idx in results for row_idx, *_ in batch)]

    def _process_batch(batch: List[Tuple[int, str, str, str]]) -> Dict[int, Dict[str, Dict[str, Optional[str]]]]:
        lines = "\n".join(
            f"{i+1}. SKU={sku} | Category={cat} | Description: {desc}"
            for i, (_, desc, sku, cat) in enumerate(batch)
        )
        prompt = _BATCH_ATTRIBUTE_EXTRACTION_PROMPT.format(products=lines)
        text = _call_gemini_rest(prompt, api_key, timeout=40.0)
        if not text:
            return {}
        parsed = _parse_json_array(text)
        if not parsed:
            return {}
        out: Dict[int, Dict[str, Dict[str, Optional[str]]]] = {}
        for i, item in enumerate(parsed):
            if i >= len(batch):
                break
            row_idx = batch[i][0]
            attr_list = item if isinstance(item, list) else [item]
            attrs: Dict[str, Dict[str, Optional[str]]] = {}
            for attr in attr_list:
                if not isinstance(attr, dict):
                    continue
                label = (attr.get("label") or "").strip()
                value = attr.get("value")
                uom = attr.get("uom")
                if label and value is not None and str(value).strip():
                    attrs[label] = {"value": str(value).strip(), "uom": str(uom).strip() if uom else None}
            if attrs:
                out[row_idx] = attrs
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_batch, b): b for b in batches}
        for future in as_completed(futures):
            try:
                batch_results = future.result(timeout=180)
                results.update(batch_results)
                _checkpoint_save(checkpoint_path, "extraction", results)
            except Exception as e:
                logger.warning("LLM attribute extraction batch failed: %s", e)

    logger.info("LLM attribute extraction complete: %d/%d products had attributes extracted.", len(results), len(items))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Shared five-format description generation
# ──────────────────────────────────────────────────────────────────────────────

_DESCRIPTION_BATCH_PROMPT = """You are a product-catalog copywriter. For each structured product below,
write five descriptions using ONLY the supplied facts. Keep every numeric value
identical across all five outputs. Return one JSON object per product, in order,
with exactly these keys: invoice_desc, mobile_desc, short_desc, long_desc1, retail_desc.

Hard format rules:
- invoice_desc: ALL CAPS, maximum 40 characters.
- mobile_desc: 60-80 characters.
- short_desc: concise ecommerce title, one sentence or phrase.
- long_desc1: a factual comma-separated specification paragraph.
- retail_desc: concise storefront summary.
- Never invent specifications, brands, or model numbers. Do not include markdown.

Products:
{products}
"""


def generate_descriptions_batch(items: List[Dict[str, Any]], batch_size: int = 20,
                                max_workers: int = 4,
                                checkpoint_path: Optional[str] = None) -> Dict[int, Dict[str, str]]:
    """Generate all five description formats in one call per batch."""
    api_key = get_api_key()
    if not api_key or not items:
        return {}
    cached = {int(key): value for key, value in _checkpoint_load(checkpoint_path, "descriptions").items()}
    items = [item for item in items if int(item["row_id"]) not in cached]
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

    def _run(batch: List[Dict[str, Any]]) -> Dict[int, Dict[str, str]]:
        lines = []
        for i, item in enumerate(batch, 1):
            lines.append(f"{i}. row_id={item['row_id']} | SKU={item['sku']} | category={item['category']} | "
                         f"description={item['description']} | brand={item.get('brand') or 'Unknown'} | "
                         f"manufacturer={item.get('manufacturer') or 'Unknown'} | attributes={json.dumps(item.get('attributes') or {}, ensure_ascii=False)}")
        text = _call_gemini_rest(_DESCRIPTION_BATCH_PROMPT.format(products="\n".join(lines)), api_key, timeout=45.0)
        parsed = _parse_json_array(text) if text else []
        out: Dict[int, Dict[str, str]] = {}
        for idx, obj in enumerate(parsed):
            if idx >= len(batch) or not isinstance(obj, dict):
                continue
            vals = {k: str(obj[k]).strip() for k in ("invoice_desc", "mobile_desc", "short_desc", "long_desc1", "retail_desc")
                    if obj.get(k) is not None and str(obj[k]).strip()}
            if vals:
                out[int(batch[idx]["row_id"])] = vals
        return out

    results: Dict[int, Dict[str, str]] = cached
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_run, b) for b in batches]
        for future in as_completed(futures):
            try:
                results.update(future.result(timeout=180))
                _checkpoint_save(checkpoint_path, "descriptions", results)
            except Exception as exc:
                logger.warning("Description generation batch failed: %s", exc)
    return results

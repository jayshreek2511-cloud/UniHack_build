"""
pipeline/uom_normalize.py — General Unit-of-Measure Normalization

Loads pipeline/reference/uom_standards.json and canonicalizes raw unit strings
(e.g. "IN", "in.", "inch", "\"", "#", "ga.", "psi", "K") to a single canonical
token that goes into ATTRIBUTE_UOM.  Category-agnostic: works for whatever units
appear across all product categories.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REF_PATH = Path(__file__).resolve().parent / "reference" / "uom_standards.json"

_cache: Optional[Dict[str, Dict[str, Any]]] = None
_synonym_map: Optional[Dict[str, str]] = None


def load_uom_standards() -> Dict[str, Dict[str, Any]]:
    """Load uom_standards.json (cached)."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_REF_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _cache = data.get("units", {})
    except Exception as e:
        logger.warning("Failed to load uom_standards.json: %s", e)
        _cache = {}
    return _cache


def _build_synonym_map() -> Dict[str, str]:
    """Build lowercase raw-uom -> canonical lookup."""
    global _synonym_map
    if _synonym_map is not None:
        return _synonym_map
    units = load_uom_standards()
    mapping: Dict[str, str] = {}
    for canonical, info in units.items():
        mapping[canonical.lower()] = canonical
        for syn in info.get("synonyms", []):
            mapping[str(syn).strip().lower()] = canonical
    _synonym_map = mapping
    return mapping


def _clean(raw: str) -> str:
    """Lowercase, strip whitespace, drop trailing period, trim quotes."""
    s = raw.strip()
    if len(s) > 1 and s.endswith("."):
        s = s[:-1]
    return s.lower()


def normalize_uom(raw: Optional[str]) -> Optional[str]:
    """Return the canonical unit token for a raw unit string, or None if blank.

    If the raw string is not in the standards table, returns a lightly cleaned
    version of the raw string rather than None, so downstream delivery still has
    a usable (if non-canonical) unit.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("null", "none", "n/a", "na"):
        return None

    # Handle the classic inch/foot marks and "#" gauge directly.
    if s == '"':
        return "in"
    if s == "'":
        return "ft"
    if s == "#" or s.lower() == "no.":
        return "#"

    clean = _clean(s)
    mapping = _build_synonym_map()
    if clean in mapping:
        return mapping[clean]

    # Fall back: strip trailing quotes (e.g. `in"` from sloppy LLM output)
    if clean.endswith('"'):
        return normalize_uom(clean[:-1])

    return s

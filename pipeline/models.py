"""
Shared data model: the single enrichment record that every pipeline stage reads/writes.

Design note: Using a dataclass (not a plain dict) so that every stage has a clear
contract on what fields exist.  New stages ADD fields; they never remove existing ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ProductRecord:
    """One row of product data as it travels through the pipeline.

    Fields present after ingestion (Stage 01):
        row_index, mfg_part_num, part_desc,
        brand_e1, brand_unilog, brand_dib, part_manuf,
        placeholder_flags

    Fields added by classification (Stage 02):
        coarse_category, is_dishwasher
    """

    # ── identity ──────────────────────────────────────────────
    row_index: int                       # 0-based position in the source CSV

    # ── raw / cleaned fields from ingestion ───────────────────
    mfg_part_num: str = ""
    part_desc: str = ""
    brand_e1: Optional[str] = None       # None ⇒ was a placeholder / missing
    brand_unilog: Optional[str] = None
    brand_dib: Optional[str] = None
    part_manuf: Optional[str] = None

    # Which brand columns were placeholder/junk in the original row
    placeholder_flags: dict = field(default_factory=dict)

    # ── classification (Stage 02) ─────────────────────────────
    coarse_category: str = "Uncategorized"
    is_dishwasher: bool = False
    classification_method: str = "rule-based"  # "rule-based" | "llm-classified"

    # ── future stages will add more fields here ───────────────

    def to_dict(self) -> dict:
        return asdict(self)

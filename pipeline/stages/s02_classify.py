"""
Stage 02 — Coarse Category Classification

Input:  List[ProductRecord] from Stage 01.
Output: The same list (mutated in-place) with `coarse_category` and `is_dishwasher`
        populated, plus a ClassificationReport summary.

Strategy (Phase 1 — deterministic, no LLM):
  Pattern-match on Part_Desc using keyword lists per category.
  First match wins (order matters — put the most specific patterns first).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from pipeline.models import ProductRecord

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Category rules: list of (category_name, compiled_regex)
# More specific patterns FIRST so they take priority.
# ──────────────────────────────────────────────────────────────────────────────

_CATEGORY_RULES: List[Tuple[str, re.Pattern]] = []


def _add_rule(category: str, pattern: str):
    _CATEGORY_RULES.append((category, re.compile(pattern, re.IGNORECASE)))


# ── Appliances — Dishwashers (MVP focus) ──────────────────────────────────
_add_rule(
    "Appliances > Large Appliances > Dishwashers",
    r"\b(dishwasher|dish\s*washer|dish\s*wash)\b"
    r"|(\bbuilt[\-\s]?in\b.*\bdish\b)"
    r"|(\btall\s*tub\b.*\bwash\b)"
    r"|(\brinse\s*aid\b)"
    r"|(\bdish\s*rack\b)"
    r"|(\bdishwash)"
)

# ── Appliances — Other ───────────────────────────────────────────────────
_add_rule(
    "Appliances > Large Appliances > Other",
    r"\b(refrigerator|freezer|washer|dryer|oven|range|stove|cooktop"
    r"|microwave|hood|ventilation)\b"
)

# ── Abrasives ─────────────────────────────────────────────────────────────
_add_rule(
    "Abrasives",
    r"\b(abrasive|sandpaper|sanding|grind(er|ing)|flap\s*disc"
    r"|cut[\-\s]?off\s*wheel|deburr|polishing\s*(wheel|disc|pad)"
    r"|grit\b)"
)

# ── Fasteners ─────────────────────────────────────────────────────────────
_add_rule(
    "Fasteners",
    r"\b(bolt|screw|nut|washer|rivet|anchor|nail|staple|clamp|fastener)\b"
)

# ── Hand Tools ────────────────────────────────────────────────────────────
_add_rule(
    "Hand Tools",
    r"\b(wrench|plier|screwdriver|hammer|chisel|file|saw|level|tape\s*measure"
    r"|hex\s*key|allen\s*key|socket\s*set)\b"
)

# ── Power Tools ───────────────────────────────────────────────────────────
_add_rule(
    "Power Tools",
    r"\b(drill|impact\s*driver|circular\s*saw|jigsaw|reciprocating"
    r"|angle\s*grinder|rotary\s*tool|power\s*tool|cordless)\b"
)

# ── Plumbing ──────────────────────────────────────────────────────────────
_add_rule(
    "Plumbing",
    r"\b(faucet|valve|pipe|fitting|toilet|sink|shower|drain|coupling"
    r"|solder|plumb)\b"
)

# ── Electrical ────────────────────────────────────────────────────────────
_add_rule(
    "Electrical",
    r"\b(wire|cable|conduit|breaker|switch|outlet|receptacle|junction\s*box"
    r"|romex|circuit|volt|amp)\b"
)

# ── Safety / PPE ──────────────────────────────────────────────────────────
_add_rule(
    "Safety & PPE",
    r"\b(glove|goggle|helmet|respirator|earplu|safety\s*glass"
    r"|high[\-\s]?vis|hard\s*hat|face\s*shield)\b"
)

# ── Adhesives & Sealants ─────────────────────────────────────────────────
_add_rule(
    "Adhesives & Sealants",
    r"\b(adhesive|sealant|caulk|epoxy|glue|silicone|tape)\b"
)

# ── Paint & Coatings ─────────────────────────────────────────────────────
_add_rule(
    "Paint & Coatings",
    r"\b(paint|primer|stain|varnish|lacquer|coating|spray\s*paint"
    r"|roller|brush)\b"
)

# ── HVAC ──────────────────────────────────────────────────────────────────
_add_rule(
    "HVAC",
    r"\b(hvac|furnace|thermostat|duct|air\s*filter|blower|compressor"
    r"|condenser|heat\s*pump)\b"
)

# ── Janitorial / Cleaning ────────────────────────────────────────────────
_add_rule(
    "Janitorial & Cleaning",
    r"\b(mop|broom|bucket|cleaner|detergent|disinfect|trash\s*bag"
    r"|janitorial|saniti)\b"
)

# ── Lighting ──────────────────────────────────────────────────────────────
_add_rule(
    "Lighting",
    r"\b(bulb|lamp|led\b|fluorescent|ballast|fixture|lumens|flood\s*light"
    r"|spot\s*light)\b"
)


# ──────────────────────────────────────────────────────────────────────────────
# Classification Report
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ClassificationReport:
    """Summary produced by the classify stage."""
    total_records: int = 0
    category_counts: Dict[str, int] = field(default_factory=dict)
    dishwasher_count: int = 0
    dishwasher_indices: List[int] = field(default_factory=list)

    def print_summary(self):
        print("\n" + "=" * 60)
        print("CATEGORY CLASSIFICATION REPORT")
        print("=" * 60)
        print(f"Total records classified: {self.total_records}")
        print(f"\n{'Category':<50} {'Count':>6}")
        print("-" * 58)
        for cat, count in sorted(
            self.category_counts.items(), key=lambda x: -x[1]
        ):
            pct = count / self.total_records * 100 if self.total_records else 0
            print(f"  {cat:<48} {count:>5}  ({pct:5.1f}%)")
        print("-" * 58)
        print(f"\nDishwasher/Appliance rows found: {self.dishwasher_count}")
        print("=" * 60 + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# Main classify function
# ──────────────────────────────────────────────────────────────────────────────

def classify(records: List[ProductRecord]) -> ClassificationReport:
    """Classify every record by pattern-matching on Part_Desc.

    Mutates each record's `coarse_category` and `is_dishwasher` fields.
    Returns a ClassificationReport with aggregate stats.
    """
    report = ClassificationReport(total_records=len(records))
    counts: Counter = Counter()

    for rec in records:
        desc = rec.part_desc or ""
        matched = False
        for category, pattern in _CATEGORY_RULES:
            if pattern.search(desc):
                rec.coarse_category = category
                matched = True
                break

        if not matched:
            rec.coarse_category = "Uncategorized"

        counts[rec.coarse_category] += 1

        # Tag dishwashers specifically
        if rec.coarse_category == "Appliances > Large Appliances > Dishwashers":
            rec.is_dishwasher = True
            report.dishwasher_indices.append(rec.row_index)

    report.category_counts = dict(counts)
    report.dishwasher_count = len(report.dishwasher_indices)

    logger.info(
        "Classification complete: %d categories, %d dishwasher rows.",
        len(counts),
        report.dishwasher_count,
    )

    return report

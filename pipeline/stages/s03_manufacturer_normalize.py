"""
Stage 03 — Manufacturer / Distributor Normalization

Input:  List[ProductRecord] (full 1,000-row dataset).
Output: Mutated records with parsed distributor info + manufacturer_list.json populated.

CRITICAL DISTINCTION (confirmed from ground truth):
    Part_Manuf in this dataset is the DISTRIBUTOR / RESELLER, NOT the actual
    product manufacturer.  For example:
        Part_Manuf = "Appliance Dealers Cooperative (APPDE)"  <-- distributor
        MANUFACTURER_NAME = "Whirlpool Corporation"           <-- real manufacturer
        BRAND_NAME = "Whirlpool"                              <-- real brand

    This stage normalizes the DISTRIBUTOR field only.  Real manufacturer/brand
    detection happens in Stage 04 (attribute extraction) using the product
    description and model number patterns.  Do NOT confuse the two downstream.

Responsibilities:
    1. Parse "Name (CODE)" pattern in Part_Manuf.
    2. Fuzzy-cluster near-duplicate distributor names.
    3. Write the normalized cluster map to manufacturer_list.json.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pipeline.models import ProductRecord

logger = logging.getLogger(__name__)

# ── Regex for "Name (CODE)" ──────────────────────────────────────────────────
_MANUF_PATTERN = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")

# Fuzzy-match threshold (0–1).  0.85 catches casing/punctuation diffs without
# false positives on genuinely different names.
_SIMILARITY_THRESHOLD = 0.82


@dataclass
class DistributorInfo:
    """Parsed + normalized distributor identity."""
    raw_value: str
    distributor_name: str            # cleaned name portion
    distributor_code: Optional[str]  # parenthetical code, if any
    cluster_id: str = ""             # canonical cluster name after fuzzy merge


@dataclass
class NormalizationReport:
    total_records: int = 0
    raw_unique_values: int = 0
    clusters_formed: int = 0
    cluster_map: Dict[str, List[str]] = field(default_factory=dict)

    def print_summary(self):
        print("\n" + "=" * 60)
        print("DISTRIBUTOR NORMALIZATION REPORT")
        print("=" * 60)
        print(f"  Total records processed:  {self.total_records}")
        print(f"  Raw unique Part_Manuf:    {self.raw_unique_values}")
        print(f"  Clusters after fuzzy:     {self.clusters_formed}")
        print(f"\n  {'Cluster (canonical)':<45} {'Members':>7}")
        print("  " + "-" * 54)
        for canonical, members in sorted(
            self.cluster_map.items(), key=lambda x: -len(x[1])
        ):
            if len(members) > 1:
                print(f"  {canonical:<45} {len(members):>5}  <-- merged")
                for m in members:
                    if m != canonical:
                        print(f"    -> {m}")
            else:
                print(f"  {canonical:<45} {len(members):>5}")
        print("=" * 60 + "\n")


def _parse_manuf(raw: Optional[str]) -> DistributorInfo:
    """Parse a raw Part_Manuf value into name + code."""
    if not raw or raw.strip() in ("", "-", "nan"):
        return DistributorInfo(
            raw_value=raw or "",
            distributor_name="Unknown",
            distributor_code=None,
        )
    raw = raw.strip()
    m = _MANUF_PATTERN.match(raw)
    if m:
        return DistributorInfo(
            raw_value=raw,
            distributor_name=m.group(1).strip(),
            distributor_code=m.group(2).strip(),
        )
    return DistributorInfo(
        raw_value=raw,
        distributor_name=raw,
        distributor_code=None,
    )


CORPORATE_SUFFIXES = {
    "inc", "co", "corp", "corporation", "llc", "ltd", "mfg", "manufacturing",
    "company", "usa", "na", "prod", "products", "dv", "g", "b", "r", "k", "5", "7"
}

def _normalize_for_comparison(name: str) -> str:
    """Lowercase, strip punctuation & corporate suffixes for fuzzy matching."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t not in CORPORATE_SUFFIXES]
    return " ".join(tokens) if tokens else s.strip()


def _similarity(a: str, b: str) -> float:
    """Combine SequenceMatcher ratio with Token Set Jaccard similarity."""
    norm_a = _normalize_for_comparison(a)
    norm_b = _normalize_for_comparison(b)
    
    seq_ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
    
    set_a = set(norm_a.split())
    set_b = set(norm_b.split())
    if set_a and set_b:
        jaccard = len(set_a & set_b) / len(set_a | set_b)
    else:
        jaccard = 0.0

    return max(seq_ratio, jaccard)


def _cluster_names(names: List[str]) -> Dict[str, List[str]]:
    """Greedy single-linkage clustering of distributor names.

    Returns {canonical_name: [all_variant_names]}.
    The longest name in each cluster becomes canonical (usually the most
    descriptive form).
    """
    clusters: List[List[str]] = []
    used = set()

    sorted_names = sorted(names, key=len, reverse=True)  # longest first

    for name in sorted_names:
        if name in used:
            continue
        cluster = [name]
        used.add(name)
        for other in sorted_names:
            if other in used:
                continue
            if _similarity(name, other) >= _SIMILARITY_THRESHOLD:
                cluster.append(other)
                used.add(other)
        clusters.append(cluster)

    result: Dict[str, List[str]] = {}
    for cluster in clusters:
        # canonical = longest (most descriptive)
        canonical = max(cluster, key=len)
        result[canonical] = sorted(cluster)

    return result


def normalize_manufacturers(
    records: List[ProductRecord],
    reference_dir: Optional[Path] = None,
) -> NormalizationReport:
    """Parse and cluster Part_Manuf across all records.

    Mutates each record by adding `distributor_info` to its data (we store
    it in the placeholder_flags dict under a new key for now, since the
    ProductRecord dataclass will be extended later).

    Writes manufacturer_list.json to reference_dir.
    """
    report = NormalizationReport(total_records=len(records))

    # ── Step 1: Parse all raw values ──────────────────────────────────────
    parsed_map: Dict[str, DistributorInfo] = {}
    for rec in records:
        raw = rec.part_manuf or ""
        if raw not in parsed_map:
            parsed_map[raw] = _parse_manuf(raw)

    report.raw_unique_values = len(parsed_map)
    logger.info("Parsed %d unique Part_Manuf values.", len(parsed_map))

    # ── Step 2: Fuzzy-cluster the distributor names ───────────────────────
    unique_names = list({info.distributor_name for info in parsed_map.values()})
    cluster_map = _cluster_names(unique_names)
    report.clusters_formed = len(cluster_map)
    report.cluster_map = cluster_map

    # Build reverse lookup: variant_name -> canonical_name
    reverse: Dict[str, str] = {}
    for canonical, members in cluster_map.items():
        for member in members:
            reverse[member] = canonical

    # ── Step 3: Assign cluster IDs back to parsed info ────────────────────
    for info in parsed_map.values():
        info.cluster_id = reverse.get(info.distributor_name, info.distributor_name)

    # ── Step 4: Tag records ───────────────────────────────────────────────
    for rec in records:
        raw = rec.part_manuf or ""
        info = parsed_map.get(raw)
        if info:
            # Store distributor metadata alongside the record
            rec.placeholder_flags["_distributor_name"] = info.distributor_name
            rec.placeholder_flags["_distributor_code"] = info.distributor_code
            rec.placeholder_flags["_distributor_cluster"] = info.cluster_id

    logger.info(
        "Clustering complete: %d raw -> %d clusters.",
        len(parsed_map), len(cluster_map),
    )

    # ── Step 5: Write manufacturer_list.json ──────────────────────────────
    if reference_dir:
        reference_dir = Path(reference_dir)
        reference_dir.mkdir(parents=True, exist_ok=True)

        output = {
            "_NOTE": (
                "This file lists DISTRIBUTORS/RESELLERS parsed from Part_Manuf. "
                "These are NOT the actual product manufacturers. Real manufacturer "
                "and brand are derived from product descriptions in Stage 04."
            ),
            "clusters": {},
            "code_lookup": {},
        }

        for canonical, members in sorted(cluster_map.items()):
            codes = set()
            for raw, info in parsed_map.items():
                if info.distributor_name in members and info.distributor_code:
                    codes.add(info.distributor_code)
            output["clusters"][canonical] = {
                "variants": members,
                "codes": sorted(codes),
            }
            for code in codes:
                output["code_lookup"][code] = canonical

        out_path = reference_dir / "manufacturer_list.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        logger.info("Wrote manufacturer_list.json -> %s", out_path)

    return report

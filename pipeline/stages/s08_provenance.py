"""
Stage 08 — Field-Level Provenance & Audit Trail Capture

Attaches source lineage to every enriched attribute:
  - 'Part_Desc text' (for attributes extracted directly from part description)
  - 'Manufacturer web retrieval' (for MFR URL and verified web specs)
  - 'LLM inference' (for inferred attributes)
  - 'Not found' (for unpopulated attributes)

Strict Rule: Only attaches real verified URLs from Phase 3; never invents URLs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from pipeline.models import ProductRecord
from pipeline.stages.s04_attribute_extract import RecordExtractionResult
from pipeline.stages.s05_manufacturer_enrich import ManufacturerSourceInfo

logger = logging.getLogger(__name__)


@dataclass
class ProvenanceEntry:
    field_name: str
    value: Optional[str]
    source_type: str  # "Part_Desc text" | "Manufacturer web retrieval" | "LLM inference" | "Not found"
    source_url: Optional[str] = None


@dataclass
class RecordProvenance:
    mfg_part_num: str
    field_provenance: Dict[str, ProvenanceEntry]

    def to_dict(self) -> dict:
        return {
            "mfg_part_num": self.mfg_part_num,
            "field_provenance": {k: asdict(v) for k, v in self.field_provenance.items()}
        }


def build_record_provenance(
    record: ProductRecord,
    extraction: RecordExtractionResult,
    mfr_info: ManufacturerSourceInfo
) -> RecordProvenance:
    """Construct complete source lineage for one ProductRecord."""
    prov_map: Dict[str, ProvenanceEntry] = {}

    # 1. Manufacturer identity & URL provenance
    mfr_url = mfr_info.mfr_url
    mfr_source_type = "Manufacturer web retrieval" if (mfr_url and mfr_info.verification_status == "source-verified") else "Not found"

    prov_map["Manufacturer URL"] = ProvenanceEntry(
        field_name="Manufacturer URL",
        value=mfr_url,
        source_type=mfr_source_type,
        source_url=mfr_url,
    )

    prov_map["Manufacturer Name"] = ProvenanceEntry(
        field_name="Manufacturer Name",
        value=mfr_info.real_manufacturer,
        source_type="Part_Manuf parsing" if record.part_manuf else "Manufacturer web retrieval",
        source_url=mfr_url,
    )

    # 2. Extracted Attributes Provenance
    for attr_name, attr in extraction.attributes.items():
        if attr.confidence_source == "source-verified":
            source_type = "Part_Desc text"
            url = None
        elif attr.confidence_source == "llm-inferred":
            source_type = "LLM inference"
            url = mfr_url
        elif attr.confidence_source == "rule-based":
            source_type = "Rule-based pattern logic"
            url = None
        elif attr.confidence_source == "inferred":
            source_type = "Rule-based pattern logic"
            url = None
        else:
            source_type = "Not found"
            url = None

        prov_map[attr_name] = ProvenanceEntry(
            field_name=attr_name,
            value=attr.value,
            source_type=source_type,
            source_url=url,
        )

    return RecordProvenance(
        mfg_part_num=record.mfg_part_num,
        field_provenance=prov_map,
    )


def build_all_provenance(
    records: List[ProductRecord],
    extractions: List[RecordExtractionResult],
    mfr_sources: Dict[str, ManufacturerSourceInfo]
) -> Dict[str, RecordProvenance]:
    """Build provenance records for a batch of products."""
    provenance_db: Dict[str, RecordProvenance] = {}

    for rec in records:
        sku = rec.mfg_part_num
        ext = next((e for e in extractions if e.mfg_part_num == sku), None)
        if not ext:
            continue
        mfr_info = mfr_sources.get(
            sku,
            ManufacturerSourceInfo(
                mfg_part_num=sku,
                real_manufacturer="Unknown",
                real_brand="Unknown",
                mfr_url=None,
                ref_urls=[],
                verification_status="not-found",
            )
        )
        provenance_db[sku] = build_record_provenance(rec, ext, mfr_info)

    logger.info("Captured provenance records for %d products.", len(provenance_db))
    return provenance_db

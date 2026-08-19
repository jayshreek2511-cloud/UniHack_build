"""
Unit tests for Phase 3 pipeline stages:
  - s05_manufacturer_enrich.py
  - s06_describe.py
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.models import ProductRecord
from pipeline.stages.s04_attribute_extract import extract_attributes
from pipeline.stages.s05_manufacturer_enrich import enrich_manufacturer_sources
from pipeline.stages.s06_describe import generate_descriptions, verify_description_consistency


class TestManufacturerEnrich:
    def test_mfr_url_retrieval(self):
        records = [
            ProductRecord(row_index=0, mfg_part_num="PDSH4816AF", part_desc="FRIGIDAIRE PDSH4816AF Dishwasher SS"),
            ProductRecord(row_index=1, mfg_part_num="KDFM404KPS", part_desc="KitchenAid KDFM404KPS Dishwasher SS"),
        ]
        sources = enrich_manufacturer_sources(records)
        assert len(sources) == 2
        assert sources["PDSH4816AF"].real_brand == "FRIGIDAIRE"
        assert sources["KDFM404KPS"].real_brand == "KitchenAid"
        # URL verification depends on live HTTP; just verify brand resolution and metadata
        assert sources["KDFM404KPS"].real_manufacturer == "Whirlpool Corporation"


class TestDescriptionGeneration:
    def test_five_descriptions_and_consistency(self):
        rec = ProductRecord(row_index=0, mfg_part_num="WDTS7024RZ", part_desc="Whirlpool WDTS7024RZ Dishwasher SS", is_dishwasher=True)
        ext = extract_attributes([rec])[0]
        mfr_info = enrich_manufacturer_sources([rec])["WDTS7024RZ"]

        descs = generate_descriptions(rec, ext, mfr_info)

        # Check all 5 formats exist
        assert len(descs.invoice_desc) <= 40
        assert descs.invoice_desc == descs.invoice_desc.upper()
        assert "Whirlpool" in descs.mobile_desc or "WDTS7024RZ" in descs.mobile_desc
        assert "WDTS7024RZ" in descs.short_desc
        assert "120 V" in descs.long_desc1
        assert "Eco Series" in descs.retail_desc

        # Consistency verification
        assert descs.consistency_passed is True
        assert len(descs.consistency_errors) == 0

    def test_consistency_failure_detection(self):
        rec = ProductRecord(row_index=0, mfg_part_num="WDTS7024RZ", part_desc="Whirlpool WDTS7024RZ Dishwasher SS", is_dishwasher=True)
        ext = extract_attributes([rec])[0]
        mfr_info = enrich_manufacturer_sources([rec])["WDTS7024RZ"]

        descs = generate_descriptions(rec, ext, mfr_info)
        # Inject conflicting voltage
        descs.long_desc1 = descs.long_desc1.replace("120 V", "220 V")

        errors = verify_description_consistency(descs, voltage="120", amperage="10", sound="41")
        assert len(errors) > 0
        assert any("Voltage inconsistency" in e for e in errors)

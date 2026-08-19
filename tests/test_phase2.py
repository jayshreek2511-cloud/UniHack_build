"""
Unit tests for Phase 2 pipeline stages:
  - s03_manufacturer_normalize.py
  - s04_attribute_extract.py
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.models import ProductRecord
from pipeline.stages.s03_manufacturer_normalize import normalize_manufacturers
from pipeline.stages.s04_attribute_extract import extract_attributes, TARGET_ATTRIBUTES


class TestManufacturerNormalize:
    def test_distributor_parsing_and_clustering(self):
        records = [
            ProductRecord(row_index=0, part_manuf="Appliance Dealers Cooperative (APPDE)"),
            ProductRecord(row_index=1, part_manuf="Freud Inc (2435)"),
            ProductRecord(row_index=2, part_manuf="Freud Inc (2435)"),
            ProductRecord(row_index=3, part_manuf="-"),
        ]
        report = normalize_manufacturers(records)
        assert report.total_records == 4
        assert report.raw_unique_values == 3  # "Appliance Dealers Cooperative (APPDE)", "Freud Inc (2435)", "-"
        assert "Appliance Dealers Cooperative" in report.cluster_map


class TestAttributeExtract:
    def test_dishwasher_attribute_extraction(self):
        records = [
            ProductRecord(row_index=0, mfg_part_num="PDSH4816AF", part_desc="PDSH4816AF FRIGIDAIRE Dishwasher SS 47dBA 120V 15A - Display Only", is_dishwasher=True),
            ProductRecord(row_index=1, mfg_part_num="WDTS7024RZ", part_desc="WDTS7024RZ Whirlpool Dishwasher SS 41dBA 120V 10A - Display Only", is_dishwasher=True),
        ]
        results = extract_attributes(records)
        assert len(results) == 2
        
        # Test PDSH4816AF
        r1 = results[0]
        assert r1.real_manufacturer == "Rheem Manufacturing"
        assert r1.real_brand == "FRIGIDAIRE"
        assert r1.attributes["Series"].value == "Professional Series"
        assert r1.attributes["Sound Level"].value == "47"
        assert r1.attributes["Sound Level"].uom == "dBA"
        assert r1.attributes["Sound Level"].confidence_source in ("inferred", "llm-inferred", "source-verified", "rule-based")
        assert r1.attributes["Voltage Rating"].confidence_source in ("inferred", "llm-inferred", "rule-based")

        # Test WDTS7024RZ
        r2 = results[1]
        assert r2.real_manufacturer == "Whirlpool Corporation"
        assert r2.real_brand == "Whirlpool"
        assert r2.attributes["Series"].value == "Eco Series"
        assert r2.attributes["Sound Level"].value == "41"
        assert r2.attributes["Sound Level"].uom == "dBA"

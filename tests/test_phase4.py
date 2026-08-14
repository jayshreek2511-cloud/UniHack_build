"""
Unit tests for Phase 4: Confidence Scoring, Provenance Capture, and Review Queue.
"""

from pathlib import Path
import pytest

from pipeline.models import ProductRecord
from pipeline.stages.s04_attribute_extract import RecordExtractionResult, ExtractedAttribute
from pipeline.stages.s05_manufacturer_enrich import ManufacturerSourceInfo
from pipeline.stages.s06_describe import GeneratedDescriptions
from pipeline.stages.s07_confidence_score import compute_record_confidence, FieldScore
from pipeline.stages.s08_provenance import build_record_provenance, ProvenanceEntry
from pipeline.stages.s09_review_queue import evaluate_record_for_review, process_review_queue


class TestConfidenceScoring:
    def test_record_confidence_calculation(self):
        ext = RecordExtractionResult(
            row_index=0,
            mfg_part_num="TEST100",
            part_desc="Test Dishwasher",
            real_manufacturer="Test Manuf",
            real_brand="Test Brand",
            attributes={
                "Sound Level": ExtractedAttribute(label="Sound Level", value="44", uom="dBA", confidence_source="source-verified"),
                "Voltage Rating": ExtractedAttribute(label="Voltage Rating", value="120", uom="V", confidence_source="inferred"),
                "Plug Type": ExtractedAttribute(label="Plug Type", value=None, uom=None, confidence_source="not-found"),
            }
        )
        mfr_info = ManufacturerSourceInfo(
            mfg_part_num="TEST100",
            real_manufacturer="Test Manuf",
            real_brand="Test Brand",
            mfr_url="https://example.com/test100",
            verification_status="source-verified",
        )

        score = compute_record_confidence(ext, mfr_info)
        assert score.mfg_part_num == "TEST100"
        assert score.field_scores["Manufacturer URL"].score == 1.0
        assert score.field_scores["Sound Level"].score == 1.0
        assert score.field_scores["Voltage Rating"].score == 0.85
        assert score.field_scores["Plug Type"].score == 0.0
        assert score.overall_score > 0.0


class TestProvenanceCapture:
    def test_field_provenance_construction(self):
        rec = ProductRecord(row_index=0, mfg_part_num="TEST100", part_desc="Test Dishwasher", part_manuf="Test Distributor")
        ext = RecordExtractionResult(
            row_index=0,
            mfg_part_num="TEST100",
            part_desc="Test Dishwasher",
            real_manufacturer="Test Manuf",
            real_brand="Test Brand",
            attributes={
                "Sound Level": ExtractedAttribute(label="Sound Level", value="44", uom="dBA", confidence_source="source-verified"),
                "Voltage Rating": ExtractedAttribute(label="Voltage Rating", value="120", uom="V", confidence_source="inferred"),
            }
        )
        mfr_info = ManufacturerSourceInfo(
            mfg_part_num="TEST100",
            real_manufacturer="Test Manuf",
            real_brand="Test Brand",
            mfr_url="https://example.com/test100",
            verification_status="source-verified",
        )

        prov = build_record_provenance(rec, ext, mfr_info)
        assert prov.mfg_part_num == "TEST100"
        assert prov.field_provenance["Manufacturer URL"].source_type == "Manufacturer web retrieval"
        assert prov.field_provenance["Manufacturer URL"].source_url == "https://example.com/test100"
        assert prov.field_provenance["Sound Level"].source_type == "Part_Desc text"
        assert prov.field_provenance["Voltage Rating"].source_type == "LLM inference"


class TestReviewQueue:
    def test_review_queue_routing_unverified_url(self):
        rec = ProductRecord(row_index=0, mfg_part_num="PDT715SYVFS", part_desc="GE Dishwasher")
        ext = RecordExtractionResult(
            row_index=0,
            mfg_part_num="PDT715SYVFS",
            part_desc="GE Dishwasher",
            real_manufacturer="GE Appliances",
            real_brand="GE Profile",
            attributes={}
        )
        mfr_info = ManufacturerSourceInfo(
            mfg_part_num="PDT715SYVFS",
            real_manufacturer="GE Appliances",
            real_brand="GE Profile",
            mfr_url=None,
            verification_status="not-found",
            needs_manual_review=True,
            http_status_code=403,
        )
        score = compute_record_confidence(ext, mfr_info)
        desc = GeneratedDescriptions(
            mfg_part_num="PDT715SYVFS",
            invoice_desc="DISHWASHER BLTLN 120V",
            mobile_desc="GE Profile, Dishwasher, PDT715SYVFS",
            short_desc="GE Profile PDT715SYVFS Dishwasher",
            long_desc1="GE Profile Dishwasher, 120 V",
            retail_desc="Dishwasher, Built-in Mounting",
            consistency_passed=True,
        )

        item = evaluate_record_for_review(rec, score, mfr_info, desc, threshold=0.75)
        assert item.status == "needs_review"
        assert any("Unverified Manufacturer URL" in r for r in item.flag_reasons)
        assert "Manufacturer URL" in item.flagged_fields

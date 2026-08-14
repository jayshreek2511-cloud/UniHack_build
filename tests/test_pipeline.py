"""
Tests for Stage 01 (Ingestion) and Stage 02 (Classification).
"""

import sys
import tempfile
from pathlib import Path

import pytest
import pandas as pd

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.models import ProductRecord
from pipeline.stages.s01_ingest import ingest
from pipeline.stages.s02_classify import classify


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a list of row-dicts to a temp CSV and return the path."""
    df = pd.DataFrame(rows)
    csv_path = tmp_path / "test.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


# ── Stage 01 Tests ────────────────────────────────────────────────────────────

class TestIngest:
    def test_basic_load(self, tmp_path):
        csv = _make_csv(tmp_path, [
            {
                "Mfg_Part_Num": "ABC123",
                "Part_Desc": "Test Widget",
                "E1_Brand": "Acme",
                "Unilog_Brand": "AcmeCo",
                "DIB_Brand": "ACME",
                "Part_Manuf": "Acme Corp",
            }
        ])
        records = ingest(csv)
        assert len(records) == 1
        assert records[0].mfg_part_num == "ABC123"
        assert records[0].brand_e1 == "Acme"

    def test_placeholder_detection(self, tmp_path):
        csv = _make_csv(tmp_path, [
            {
                "Mfg_Part_Num": "X1",
                "Part_Desc": "Some Part",
                "E1_Brand": "-- Unbranded --",
                "Unilog_Brand": "-- No Unilog Brand --",
                "DIB_Brand": "-- No DIB Brand --",
                "Part_Manuf": "RealManuf",
            }
        ])
        records = ingest(csv)
        r = records[0]
        assert r.brand_e1 is None
        assert r.brand_unilog is None
        assert r.brand_dib is None
        assert r.part_manuf == "RealManuf"
        assert r.placeholder_flags["brand_e1"] is True
        assert r.placeholder_flags["part_manuf"] is False

    def test_missing_columns_raises(self, tmp_path):
        csv = _make_csv(tmp_path, [
            {"Mfg_Part_Num": "X"}  # missing Part_Desc col
        ])
        with pytest.raises(ValueError, match="missing required columns"):
            ingest(csv)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ingest("/nonexistent/path.csv")


# ── Stage 02 Tests ────────────────────────────────────────────────────────────

class TestClassify:
    def _make_record(self, desc: str, idx: int = 0) -> ProductRecord:
        return ProductRecord(row_index=idx, part_desc=desc)

    def test_dishwasher_detected(self):
        records = [
            self._make_record("24 in. Built-In Dishwasher with Stainless Steel"),
            self._make_record("Some random abrasive disc"),
        ]
        report = classify(records)
        assert records[0].is_dishwasher is True
        assert records[0].coarse_category == "Appliances > Large Appliances > Dishwashers"
        assert records[1].is_dishwasher is False
        assert report.dishwasher_count == 1

    def test_abrasive_detected(self):
        records = [self._make_record("4-1/2 in. Flap Disc 80 Grit")]
        report = classify(records)
        assert records[0].coarse_category == "Abrasives"

    def test_uncategorized_fallback(self):
        records = [self._make_record("Mystery Widget XYZ")]
        report = classify(records)
        assert records[0].coarse_category == "Uncategorized"

    def test_report_counts(self):
        records = [
            self._make_record("Dishwasher Model A", 0),
            self._make_record("Dishwasher Model B", 1),
            self._make_record("Sandpaper 120 Grit", 2),
        ]
        report = classify(records)
        assert report.total_records == 3
        assert report.dishwasher_count == 2
        assert report.category_counts.get("Abrasives") == 1

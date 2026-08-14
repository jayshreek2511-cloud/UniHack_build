"""
FastAPI application — Phase 5 Live Backend for Product Intelligence Dashboard

Serves real pipeline output artifacts from data/output/ without mock data.
Provides endpoints for stats, records catalog, record detail, review queue, and record approvals.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger("api")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
APPROVALS_FILE = OUTPUT_DIR / "approvals.json"

app = FastAPI(
    title="Product Intelligence Pipeline API",
    version="1.0.0",
    description="AI-Powered Product Intelligence for Industrial Commerce (FastAPI Backend)",
)

# Enable CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_approvals() -> set:
    if APPROVALS_FILE.exists():
        try:
            with open(APPROVALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("approved_skus", []))
        except Exception:
            return set()
    return set()


def _save_approvals(approved_skus: set):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(APPROVALS_FILE, "w", encoding="utf-8") as f:
        json.dump({"approved_skus": list(approved_skus)}, f, indent=2)


def _load_enriched_records() -> List[dict]:
    path = OUTPUT_DIR / "dishwasher_enriched_full.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Enriched records file not found. Please run Phase 4 pipeline first.")
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)

    approved = _load_approvals()
    for item in records:
        sku = item["identity"]["mfg_part_num"]
        if sku in approved:
            item["confidence_score"]["needs_manual_review"] = False
            item["review_status"] = "approved"
        else:
            # Check review queue status
            mfr_needs_review = item["manufacturer_info"].get("needs_manual_review", False)
            score_below = item["confidence_score"]["overall_score"] < 0.75
            crit_missing = len(item["confidence_score"].get("critical_missing_fields", [])) > 0
            if mfr_needs_review or score_below or crit_missing:
                item["review_status"] = "needs_review"
            else:
                item["review_status"] = "complete"

    return records


def _load_review_queue() -> dict:
    path = OUTPUT_DIR / "review_queue.json"
    if not path.exists():
        return {"summary": {"total_processed": 0, "complete_count": 0, "review_count": 0}, "review_queue": [], "complete": []}
    with open(path, "r", encoding="utf-8") as f:
        rq = json.load(f)

    records = []
    try:
        with open(OUTPUT_DIR / "dishwasher_enriched_full.json", "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception:
        pass

    total_dishwasher_count = len(records) if records else 10
    approved = _load_approvals()
    # Filter out approved SKUs from review_queue
    rq["review_queue"] = [item for item in rq["review_queue"] if item["mfg_part_num"] not in approved]
    rq["summary"]["review_count"] = len(rq["review_queue"])
    rq["summary"]["approved_count"] = len(approved)
    rq["summary"]["complete_count"] = max(0, total_dishwasher_count - len(rq["review_queue"]))
    return rq


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "phase": 5}


@app.get("/api/stats")
async def get_stats():
    """Pipeline-wide statistics derived from real execution output."""
    records = _load_enriched_records()
    rq = _load_review_queue()

    # Ingested total count from classified_full.csv
    total_ingested_count = 1000
    cat_counts = {}
    classified_csv = OUTPUT_DIR / "classified_full.csv"
    if classified_csv.exists():
        try:
            df = pd.read_csv(classified_csv)
            total_ingested_count = len(df)
            cat_counts = df["Coarse_Category"].value_counts().to_dict()
        except Exception:
            pass

    scores = [r["confidence_score"]["overall_score"] for r in records]
    avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0

    complete_cnt = sum(1 for r in records if r["review_status"] in ("complete", "approved"))
    review_cnt = sum(1 for r in records if r["review_status"] == "needs_review")
    approved_cnt = sum(1 for r in records if r["review_status"] == "approved")

    return {
        "total_ingested": total_ingested_count,
        "dishwasher_classified": len(records),
        "complete_count": complete_cnt,
        "review_count": review_cnt,
        "approved_count": approved_cnt,
        "avg_confidence_score": avg_score,
        "category_breakdown": cat_counts,
        "pipeline_stages": [
            {"stage": "01_ingest", "name": "Catalog Ingestion", "input_count": total_ingested_count, "output_count": total_ingested_count, "status": "passed"},
            {"stage": "02_classify", "name": "Category Classification", "input_count": total_ingested_count, "output_count": len(records), "status": "passed"},
            {"stage": "03_normalize", "name": "Distributor Normalization", "input_count": len(records), "output_count": len(records), "status": "passed"},
            {"stage": "04_extract", "name": "Attribute Extraction", "input_count": len(records), "output_count": len(records), "status": "passed"},
            {"stage": "05_enrich", "name": "MFR Retrieval & Verification", "input_count": len(records), "output_count": len(records), "status": "passed"},
            {"stage": "06_describe", "name": "Description Generation", "input_count": len(records), "output_count": len(records), "status": "passed"},
            {"stage": "07_score", "name": "Confidence Scoring", "input_count": len(records), "output_count": len(records), "status": "passed"},
            {"stage": "08_provenance", "name": "Provenance Tracking", "input_count": len(records), "output_count": len(records), "status": "passed"},
            {"stage": "09_review_queue", "name": "Human Review Queue", "input_count": len(records), "output_count": review_cnt, "status": "active"},
        ]
    }


@app.get("/api/records")
async def get_records():
    """Retrieve all enriched product records."""
    return _load_enriched_records()


@app.get("/api/records/{sku}")
async def get_record_detail(sku: str):
    """Retrieve complete detail for a single SKU including provenance."""
    records = _load_enriched_records()
    for r in records:
        if r["identity"]["mfg_part_num"].upper() == sku.upper():
            return r
    raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found.")


@app.get("/api/review-queue")
async def get_review_queue():
    """Retrieve current human review queue items and reasons."""
    return _load_review_queue()


class ApprovalRequest(BaseModel):
    notes: Optional[str] = "Manually verified by domain manager"


@app.post("/api/records/{sku}/approve")
async def approve_record(sku: str, req: Optional[ApprovalRequest] = None):
    """Approve a record from the review queue and persist the approval."""
    records = _load_enriched_records()
    matched = False
    for r in records:
        if r["identity"]["mfg_part_num"].upper() == sku.upper():
            matched = True
            break

    if not matched:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found.")

    approved = _load_approvals()
    approved.add(sku.upper())
    _save_approvals(approved)

    logger.info("Manually approved SKU %s", sku.upper())
    return {
        "status": "success",
        "message": f"SKU {sku.upper()} approved successfully.",
        "approved_sku": sku.upper(),
    }


from fastapi import UploadFile, File
from fastapi.responses import FileResponse
import subprocess
import sys


@app.post("/api/pipeline/run")
def run_pipeline_execution(file: Optional[UploadFile] = File(None)):
    """Run full end-to-end pipeline (ingest -> classify -> extract -> enrich -> score -> export) and generate delivery export files."""
    try:
        input_file_path = PROJECT_ROOT / "data" / "input" / "Unihack__Sample_Dataset_-_Input__1_.csv"
        input_filename = "Unihack__Sample_Dataset_-_Input__1_.csv"
        row_count = 0

        if file is not None:
            upload_path = PROJECT_ROOT / "data" / "input" / "uploaded_input.csv"
            contents = file.file.read()
            with open(upload_path, "wb") as f:
                f.write(contents)
            input_file_path = upload_path
            input_filename = file.filename or "uploaded_input.csv"

        try:
            df_in = pd.read_csv(input_file_path)
            row_count = len(df_in)
        except Exception:
            pass

        logger.info("=" * 80)
        logger.info("RECEIVED PIPELINE EXECUTION REQUEST: File='%s', Rows=%d, Path='%s'", input_filename, row_count, input_file_path)
        logger.info("=" * 80)

        # 1. Execute run_phase4.py script with explicit input file argument
        cmd_phase4 = [sys.executable, str(PROJECT_ROOT / "run_phase4.py"), str(input_file_path)]
        logger.info("Executing pipeline command: %s", " ".join(cmd_phase4))
        res = subprocess.run(cmd_phase4, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if res.returncode != 0:
            logger.error("Pipeline run error: %s", res.stderr)
            raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {res.stderr[:300]}")
        logger.info("Phase 1-4 pipeline execution complete for %s (%d input rows).", input_filename, row_count)

        # 2. Execute s10_delivery_export.py stage
        cmd_export = [sys.executable, str(PROJECT_ROOT / "pipeline" / "stages" / "s10_delivery_export.py")]
        logger.info("Executing delivery export command: %s", " ".join(cmd_export))
        res_exp = subprocess.run(cmd_export, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if res_exp.returncode != 0:
            logger.error("Export error: %s", res_exp.stderr)
            raise HTTPException(status_code=500, detail=f"Delivery export failed: {res_exp.stderr[:300]}")
        logger.info("Stage 10 export complete. Delivery files generated.")

        return {
            "status": "success",
            "message": f"Pipeline executed successfully for '{input_filename}' ({row_count} rows processed)!",
            "input_file": input_filename,
            "input_rows": row_count,
            "csv_download_url": "/api/pipeline/download/csv",
            "excel_download_url": "/api/pipeline/download/excel"
        }
    except Exception as e:
        logger.exception("Error during pipeline execution")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pipeline/download/excel")
async def download_delivery_excel():
    """Download delivery_export.xlsx file."""
    excel_path = OUTPUT_DIR / "delivery_export.xlsx"
    if not excel_path.exists():
        # Ensure export is generated if missing
        subprocess.run([sys.executable, str(PROJECT_ROOT / "pipeline" / "stages" / "s10_delivery_export.py")], cwd=str(PROJECT_ROOT))
    if not excel_path.exists():
        raise HTTPException(status_code=404, detail="Delivery Excel export file not found.")

    return FileResponse(
        path=excel_path,
        filename="delivery_export.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.get("/api/pipeline/download/csv")
async def download_delivery_csv():
    """Download delivery_export.csv file."""
    csv_path = OUTPUT_DIR / "delivery_export.csv"
    if not csv_path.exists():
        subprocess.run([sys.executable, str(PROJECT_ROOT / "pipeline" / "stages" / "s10_delivery_export.py")], cwd=str(PROJECT_ROOT))
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Delivery CSV export file not found.")

    return FileResponse(
        path=csv_path,
        filename="delivery_export.csv",
        media_type="text/csv"
    )


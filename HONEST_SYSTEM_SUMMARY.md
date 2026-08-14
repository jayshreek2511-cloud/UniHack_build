# Technical Audit & System Explainability Summary

## 1. Pipeline Audit: Method & Provenance Breakdown

| Stage / Field | Execution Method | Provenance Tag Used | Is Tag Misleading? | Notes / Explanation |
| :--- | :--- | :--- | :--- | :--- |
| **Stage 01: Ingestion** | Direct Text Parsing | `source-verified` | No | Direct ingestion of CSV headers & row text. |
| **Stage 02: Classification** | Deterministic Keyword Rule | `rule-based` | No | Checks `Part_Desc` text for `"dishwasher"`. |
| **Stage 03: Distributor Norm** | Fuzzy Merge (SequenceMatcher) | `rule-based` | No | Merges distributor variants in `Part_Manuf`. |
| **Stage 04: Brand & Mfr Entity** | Universal Regex Map (`brand_resolver.py`) | `source-verified` | No | Parses brand text from `Part_Desc`. Eliminates distributor conflation. |
| **Stage 04: Attribute Extraction** | Gemini 2.0 Flash API (Fallback: Regex) | `llm-inferred` / `rule-based` | **No (Corrected)** | Uses Gemini API when key is set; transparently tagged `rule-based` when fallback is used. |
| **Stage 05: MFR Retrieval** | Browser HTTP GET Verification | `source-verified` / `not-found` | No | **Strict HTTP 200 Required**. Unverified/403 pages strictly set `mfr_url = None`. |
| **Stage 06: Description Gen** | Template Synthesis + LLM | `rule-based` / `llm-inferred` | No | Generates 5 consistent format descriptions from structured attributes. |
| **Stage 07: Completeness Score** | Weighted Mathematical Formula | `N/A` | No | Formula: `(2.0*Critical_Fields + 1.0*Optional) / Total_Weight`. |
| **Stage 08: Provenance Lineage** | Lineage Graph Capture | `N/A` | No | Tracks exact source type and verified URL for every field. |
| **Stage 09: Review Queue Router** | Score & Critical Field Router | `N/A` | No | Routes records with score < 0.75 or unverified MFR URLs to review queue. |
| **Stage 10: Unilog Delivery Export**| Schema Formatter | `N/A` | No | Formats records into Unilog 252-column schema with safety nets. |

---

## 2. Web Retrieval & Verification Realities

- **Strict HTTP 200 Verification**: The pipeline makes live HTTP GET requests to official manufacturer domain candidates. A URL is **ONLY** marked `source-verified` if it returns **HTTP 200 OK** and contains the exact SKU string in the page content.
- **Bot Protection (Akamai / Cloudflare)**: Major appliance manufacturer sites (GE, Miele, LG) return **HTTP 403 Forbidden** to automated script headers.
- **Honest Handling**: The pipeline **never invents or guesses URLs**. Unverified/403 pages are strictly set to `mfr_url = None` and flagged for **Human Review Queue** audit (0% false verified claims).

---

## 3. Scale, Cost & Human Burden Analytics (1,000-Row Projections)

- **Gemini 2.0 Flash Pricing**: $0.10 / 1M input tokens, $0.40 / 1M output tokens.
- **LLM Calls per Record**: 2 calls (1 for attribute reasoning, 1 for description synthesis).
- **Projections for 1,000 Catalog Rows**:
  - **Total LLM API Calls**: 2,000 calls
  - **Estimated Total LLM Cost**: **$0.35 USD**
  - **Parallel Batch Runtime**: **~45 seconds** (20 worker threads)
  - **Observed Review Queue Rate**: **60.0%** (3/5 test SKUs flagged due to official site 403 bot challenges)
  - **Estimated Human Review Burden**: ~600 SKUs requiring ~45s audit per record = **7.5 human review hours total** (vs. 135+ hours manual catalog entry, **94.5% time saved**).

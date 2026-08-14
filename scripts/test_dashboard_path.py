import httpx
import os
import datetime
import pandas as pd

API_URL = "http://127.0.0.1:8000/api/pipeline/run"
DOWNLOAD_URL = "http://127.0.0.1:8000/api/pipeline/download/csv"
UPLOAD_FILE_PATH = "data/input/uploaded_input.csv"

print("=" * 90)
print("EXECUTION TEST: RUNNING PIPELINE VIA DASHBOARD API ENDPOINT")
print("=" * 90)

# 1. Trigger POST /api/pipeline/run uploading 40-row test dataset
print(f"1. Sending POST request to {API_URL} with file '{UPLOAD_FILE_PATH}'...")
with open(UPLOAD_FILE_PATH, "rb") as f:
    files = {"file": ("uploaded_input.csv", f, "text/csv")}
    resp = httpx.post(API_URL, files=files, timeout=120.0)

print(f"   API Response Status: {resp.status_code}")
print(f"   API Response Payload: {resp.json()}\n")

# 2. Trigger GET /api/pipeline/download/csv
print(f"2. Sending GET request to download endpoint: {DOWNLOAD_URL}...")
resp_down = httpx.get(DOWNLOAD_URL, timeout=30.0)
print(f"   Download Status: {resp_down.status_code}")

# Save downloaded CSV
save_path = "data/output/dashboard_download_verification.csv"
with open(save_path, "wb") as f:
    f.write(resp_down.content)

print(f"   Downloaded file saved to '{save_path}'")

# 3. Read downloaded file and inspect SKUs
df_downloaded = pd.read_csv(save_path)

print("\n" + "=" * 90)
print(f"VERIFICATION RESULTS FOR DOWNLOAD FILE ('{save_path}')")
print("=" * 90)
print(f"File Timestamp : {datetime.datetime.fromtimestamp(os.path.getmtime(save_path))}")
print(f"Total Row Count: {len(df_downloaded)} rows")
print("\nFull SKU List at Download Path:")
for idx, row in df_downloaded.iterrows():
    sku = row["Mfg_Part_Num"]
    brand = row.get("BRAND_NAME", "N/A")
    mfr = row.get("MANUFACTURER_NAME", "N/A")
    url = str(row.get("MFR URL"))
    print(f"  Row {idx:2d} | SKU: {sku:12s} | Brand: {str(brand):16s} | Mfr: {str(mfr):25s} | MFR URL: {url[:45]}")

print("=" * 90)

# Assert DD24SDFT9N is present
skus = list(df_downloaded["Mfg_Part_Num"])
assert "DD24SDFT9N" in skus, "DD24SDFT9N is missing from downloaded CSV!"
assert len(skus) == 15, f"Expected 15 rows, found {len(skus)}"
print("\nSUCCESS! DD24SDFT9N IS PRESENT AND FILE CONTAINS EXACTLY 15 ROWS.")

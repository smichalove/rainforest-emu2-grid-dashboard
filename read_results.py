import os
import json
from google.cloud import storage

PROJECT_ID = "mutua-477100"
BUCKET_NAME = "mutua-477100-batch-images"
PREFIX = "dashboard_emulation_output/"
SA_PATH = "/Users/treven/Documents/rainforest-emu2-grid-dashboard/Auth/service_account.json"

def main():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SA_PATH
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    
    blobs = list(bucket.list_blobs(prefix=PREFIX))
    print(f"Found {len(blobs)} files in gs://{BUCKET_NAME}/{PREFIX}")
    
    # We want to find the output files. Typically Vertex Batch writes output files ending with something like .jsonl
    # Let's inspect the files.
    for blob in blobs:
        if blob.name.endswith(".jsonl") or "prediction-" in blob.name:
            print(f"\n--- Reading {blob.name} ({blob.size} bytes) ---")
            content = blob.download_as_text()
            lines = content.strip().split("\n")
            print(f"Total lines: {len(lines)}")
            # Show a sample of the first line or output
            if lines:
                try:
                    data = json.loads(lines[0])
                    # Depending on model output format, let's see what keys are present
                    print("Sample keys:", data.keys())
                    if "response" in data:
                        resp = data["response"]
                        if "candidates" in resp:
                            cand = resp["candidates"][0]
                            if "content" in cand:
                                parts = cand["content"]["parts"]
                                print("Output sample:", parts[0].get("text", "")[:300])
                    elif "error" in data:
                        print("Error in response:", data["error"])
                except Exception as e:
                    print(f"Error parsing json/output: {e}")
                    print("Raw line sample:", lines[0][:300])

if __name__ == "__main__":
    main()

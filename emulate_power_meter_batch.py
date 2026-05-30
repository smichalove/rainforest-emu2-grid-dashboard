import os
import json
import time
import datetime
import csv
import sys
from google.cloud import storage
import google.genai as genai
from google.genai import types

# Configurations matching user's GCP environment
PROJECT_ID = "mutua-477100"
LOCATION = "global"
MODEL_NAME = "gemini-2.5-flash"
BUCKET_NAME = "mutua-477100-batch-images"
NUM_BATCHES = 10
REQUESTS_PER_BATCH = 15

def load_credentials():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sa_path = os.path.join(script_dir, "Auth/service_account.json")
    if os.path.exists(sa_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_path
        print(f"✅ Set GOOGLE_APPLICATION_CREDENTIALS to {sa_path}")
    else:
        print(f"❌ Service account not found at {sa_path}")
        sys.exit(1)

def generate_mock_prompts():
    print("Reading history data and prompt template...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, "gemini_prompt.txt")
    
    with open(prompt_path, "r", encoding="utf-8") as pf:
        prompt_template = pf.read()

    # Load history file to construct realistic aggregations
    history_file = os.path.join(script_dir, "grid_history.csv")
    rows = []
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            reader = csv.reader(f)
            for r in reader:
                if len(r) == 2:
                    rows.append(r)
    
    print(f"Read {len(rows)} history rows.")
    
    prompts = []
    now = datetime.datetime.now()
    
    # We will generate total of NUM_BATCHES * REQUESTS_PER_BATCH = 150 requests.
    # To make them realistic, we construct different simulated hourly CSV blocks.
    for i in range(NUM_BATCHES * REQUESTS_PER_BATCH):
        # Construct a mini 24h CSV history block with slightly varying values
        csv_lines = ["Hour,Avg_kW,Min_kW,Max_kW,Median_kW,SE_Avg_kW,SE_Max_kW,SE_Energy_kWh,Battery_Avg_kW,Battery_SoC,Chillicon_Avg_kW,Chillicon_Max_kW,Chillicon_Energy_kWh"]
        for hour in range(24):
            hour_str = f"2026-05-27 {hour:02d}:00"
            avg_kw = -1.5 + (hour % 3) * 0.5 + (i * 0.01)
            min_kw = avg_kw - 0.5
            max_kw = avg_kw + 0.5
            se_avg = 1.2 if 8 <= hour <= 17 else 0.0
            ch_avg = 1.0 if 8 <= hour <= 17 else 0.0
            bat_avg = 0.5 if hour == 18 else 0.0
            csv_lines.append(f"{hour_str},{avg_kw:.3f},{min_kw:.3f},{max_kw:.3f},{avg_kw:.3f},{se_avg:.3f},{se_avg:.3f},{se_avg:.3f},{bat_avg:.3f},90.0,{ch_avg:.3f},{ch_avg:.3f},{ch_avg:.3f}")
        
        csv_data = "\n".join(csv_lines)
        
        current_dt_str = now.strftime("%Y-%m-%d %H:%M:%S")
        last_dt_str = now.strftime("%Y-%m-%d %H:%M:%S")
        first_dt_str = "2026-05-27 00:00:00"
        
        prompt = prompt_template.format(
            csv_data=csv_data,
            current_date_time=current_dt_str,
            last_data_time=last_dt_str,
            first_data_time=first_dt_str
        )
        
        prompts.append({
            "request_id": f"power_meter_query_{i:03d}_{int(time.time())}",
            "request": {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": "You are a precise grid monitor summarizer."}]}
            }
        })
        
    return prompts

def upload_to_gcs(local_path, gcs_path):
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(local_path)
    return f"gs://{BUCKET_NAME}/{gcs_path}"

def main():
    load_credentials()
    prompts = generate_mock_prompts()
    
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    print("\n" + "="*50)
    print(" STARTING BATCH SUBMISSION EMULATION")
    print("="*50)
    
    local_manifest_paths = []
    job_ids = []
    
    start_time = time.time()
    
    # 1. Group prompts into 10 batches and write to JSONL locally
    for batch_idx in range(NUM_BATCHES):
        batch_prompts = prompts[batch_idx * REQUESTS_PER_BATCH : (batch_idx + 1) * REQUESTS_PER_BATCH]
        local_path = f"batch_request_{batch_idx}.jsonl"
        with open(local_path, "w", encoding="utf-8") as f:
            for p in batch_prompts:
                f.write(json.dumps(p) + "\n")
        local_manifest_paths.append(local_path)
        
    local_prep_time = time.time() - start_time
    print(f"⏱️ Local JSONL preparation time: {local_prep_time:.4f} seconds")
    
    # 2. Upload to GCS and Submit to Vertex AI global location
    upload_and_sub_start = time.time()
    for batch_idx, local_path in enumerate(local_manifest_paths):
        gcs_path = f"dashboard_emulation/batch_{batch_idx}_{int(time.time())}.jsonl"
        print(f"Uploading Batch {batch_idx+1}/{NUM_BATCHES} to GCS...")
        gcs_uri = upload_to_gcs(local_path, gcs_path)
        
        dest_uri = f"gs://{BUCKET_NAME}/dashboard_emulation_output/batch_{batch_idx}_{int(time.time())}/"
        
        print(f"Submitting Batch {batch_idx+1} to Vertex AI global location...")
        try:
            batch_job = client.batches.create(
                model=MODEL_NAME,
                src=gcs_uri,
                config={'dest': dest_uri}
            )
            print(f"  ✅ Created Job: {batch_job.name}")
            print(f"  State: {batch_job.state}")
            job_ids.append(batch_job.name)
        except Exception as e:
            print(f"  ❌ Failed to create job: {e}")
            
        # Cleanup local file
        if os.path.exists(local_path):
            os.remove(local_path)
            
    total_sub_time = time.time() - upload_and_sub_start
    print(f"\n⏱️ Total Upload & Submission time: {total_sub_time:.4f} seconds")
    print(f"⏱️ Total local execution pipeline time: {time.time() - start_time:.4f} seconds")
    
    # Save job list for polling
    with open("emulated_jobs.json", "w") as f:
        json.dump(job_ids, f, indent=4)
        
    # 3. Cost Analysis based on Pricing and tokens
    # Model: gemini-2.5-flash
    # Standard: $0.075 / 1M input | $0.30 / 1M output
    # Batch (50% off): $0.0375 / 1M input | $0.150 / 1M output
    # Let's count characters of the prompt to estimate tokens
    avg_prompt_chars = len(prompts[0]["request"]["contents"][0]["parts"][0]["text"])
    estimated_input_tokens_per_request = int(avg_prompt_chars / 4)
    estimated_output_tokens_per_request = 200 # Average summary output size
    
    total_requests = NUM_BATCHES * REQUESTS_PER_BATCH
    total_input_tokens = total_requests * estimated_input_tokens_per_request
    total_output_tokens = total_requests * estimated_output_tokens_per_request
    
    std_input_cost = (total_input_tokens / 1_000_000) * 0.075
    std_output_cost = (total_output_tokens / 1_000_000) * 0.300
    std_total_cost = std_input_cost + std_output_cost
    
    batch_input_cost = (total_input_tokens / 1_000_000) * 0.0375
    batch_output_cost = (total_output_tokens / 1_000_000) * 0.150
    batch_total_cost = batch_input_cost + batch_output_cost
    
    print("\n" + "="*50)
    print(" COST BENEFIT & LATENCY ANALYSIS")
    print("="*50)
    print(f"Total Requests Emulated: {total_requests}")
    print(f"Est. Input Tokens: {total_input_tokens:,} | Est. Output Tokens: {total_output_tokens:,}")
    print("-" * 50)
    print(f"Standard API Cost: ${std_total_cost:.6f}")
    print(f"Batch API Cost:    ${batch_total_cost:.6f} (50% Cost Savings!)")
    print(f"Savings:           ${std_total_cost - batch_total_cost:.6f}")
    print("="*50)
    
    print("\nNow polling Vertex AI for job status baseline...")
    # Poll until complete or up to a short duration to measure initial queue latency
    poll_start = time.time()
    for _ in range(6): # Poll 6 times, waiting 15s in between
        print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Checking status...")
        all_done = True
        for idx, job_name in enumerate(job_ids):
            try:
                job = client.batches.get(name=job_name)
                print(f"  Job {idx+1}: {job.state}")
                if job.state not in ["SUCCEEDED", "FAILED"]:
                    all_done = False
            except Exception as e:
                print(f"  Error checking job {idx+1}: {e}")
        if all_done:
            print("🎉 All emulation jobs finished processing!")
            break
        time.sleep(15)
        
    print(f"\nInitial status check complete. List of Job Resource Names saved in emulated_jobs.json.")

if __name__ == "__main__":
    main()

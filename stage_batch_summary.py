import os
import json
import time
import datetime
import csv
import statistics
import threading
import sys
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
from google.cloud import storage
import google.genai as genai
from google.genai import types

from dashboard_modules import ai

# Path configuration relative to script directory to ensure portability
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))

# Load local .env file dynamically if it exists
env_path = os.path.join(SCRIPT_DIR, ".env")
if os.path.exists(env_path):
    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as env_err:
        print(f"Warning: Could not parse local .env file: {env_err}")

# -------------------------------------------------------------
# Configuration Constants (Pulling from Environment/Defaults)
# -------------------------------------------------------------
LOCATION: str = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
MODEL_NAME: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
BUCKET_NAME: str = os.environ.get("GEMINI_BATCH_BUCKET", "mutua-477100-batch-images")
PROJECT_ID: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "mutua-477100")
BATCH_INTERVAL_HOURS: int = int(os.environ.get("BATCH_INTERVAL_HOURS", "4"))

GEMINI_SUMMARY_CACHE: str = os.path.join(SCRIPT_DIR, "gemini_summary.json")
ACTIVE_BATCH_STATE: str = os.path.join(SCRIPT_DIR, "active_batch_job.json")

# Local Telemetry CSV History Paths (Matching dashboard.py dynamic resolver)
HOME_DIR: str = os.path.expanduser("~")
LOCAL_GRID: str = os.path.join(SCRIPT_DIR, "grid_history.db")
GRID_HISTORY: str = LOCAL_GRID if os.path.exists(LOCAL_GRID) else os.path.join(HOME_DIR, "grid_history.db")

LOCAL_SE: str = os.path.join(SCRIPT_DIR, "solaredge_history.csv")
SE_HISTORY: str = LOCAL_SE if os.path.exists(LOCAL_SE) else os.path.join(HOME_DIR, "solaredge_history.csv")

LOCAL_SE_BATTERY: str = os.path.join(SCRIPT_DIR, "solaredge_battery_history.csv")
SE_BATTERY_HISTORY: str = LOCAL_SE_BATTERY if os.path.exists(LOCAL_SE_BATTERY) else os.path.join(HOME_DIR, "solaredge_battery_history.csv")

LOCAL_CHILICON: str = os.path.join(SCRIPT_DIR, "chilicon_history.csv")
CHILICON_HISTORY: str = LOCAL_CHILICON if os.path.exists(LOCAL_CHILICON) or not os.path.exists(os.path.join(HOME_DIR, "chilicon_history.csv")) else os.path.join(HOME_DIR, "chilicon_history.csv")


def setup_credentials() -> None:
    """Configures the local environment to authenticate Google Cloud API calls.

    Searches multiple potential local directories for the service account JSON key file,
    setting the GOOGLE_APPLICATION_CREDENTIALS environment variable.

    Args:
        None

    Returns:
        None

    Raises:
        SystemExit: If the service account JSON key file is missing in all search paths.
    """
    global PROJECT_ID
    home_dir: str = os.path.expanduser("~")
    possible_paths: List[str] = [
        os.path.join(SCRIPT_DIR, "Auth/service_account.json"),
        os.path.join(SCRIPT_DIR, "auth/service_account.json"),
        os.path.join(SCRIPT_DIR, "../Auth/service_account.json"),
        os.path.join(SCRIPT_DIR, "../auth/service_account.json"),
        os.path.join(home_dir, "Auth/service_account.json"),
        os.path.join(home_dir, "auth/service_account.json")
    ]
    
    sa_path: Optional[str] = None
    for path in possible_paths:
        if os.path.exists(path):
            sa_path = path
            break
            
    if sa_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_path
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Auth: Set credentials path to {sa_path}")
        
        # Auto-extract project_id from service account JSON if not explicitly provided in environment
        if "GOOGLE_CLOUD_PROJECT" not in os.environ:
            try:
                with open(sa_path, 'r') as key_file:
                    sa_data = json.load(key_file)
                    extracted_project = sa_data.get("project_id")
                    if extracted_project:
                        PROJECT_ID = extracted_project
                        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Auth: Extracted project_id '{PROJECT_ID}' from service account.")
            except Exception as json_err:
                print(f"Auth Warning: Could not parse project_id from service account JSON: {json_err}")
    else:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ERROR: Credentials file not found in any search paths.")
        sys.exit(1)

def generate_hourly_summaries() -> str:
    """Parses local CSV logs and computes hourly min, max, avg, and median telemetry statistics.

    Extracts, aligns, and aggregates rainforest grid demand, SolarEdge solar, SolarEdge
    battery state, and Chillicon production records from CSV history files.

    Args:
        None

    Returns:
        A compact CSV string where each row represents one hour of aligned data.

    Raises:
        None
    """
    return ai.generate_hourly_summaries(GRID_HISTORY, SE_HISTORY, SE_BATTERY_HISTORY, CHILICON_HISTORY)

def upload_to_gcs(local_path: str, gcs_path: str) -> str:
    """Uploads a local manifest or configuration file to Google Cloud Storage."""
    return ai.upload_to_gcs(local_path, gcs_path, BUCKET_NAME, PROJECT_ID)

def gcs_cleanup_loop() -> None:
    """Background daemon loop that removes GCS inputs and predictions older than 24 hours.

    Runs continuously, waking up once every 24 hours to clean up disk storage.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    while True:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] GCS Cleanup: Starting run...")
        try:
            storage_client = storage.Client(project=PROJECT_ID)
            bucket = storage_client.bucket(BUCKET_NAME)
            now_utc: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
            cutoff: datetime.datetime = now_utc - datetime.timedelta(hours=24)
            
            deleted_count: int = 0
            for prefix in ["dashboard_emulation/", "dashboard_emulation_output/"]:
                blobs = list(bucket.list_blobs(prefix=prefix))
                for blob in blobs:
                    # Compares creation/modification time in UTC
                    if blob.updated < cutoff:
                        blob.delete()
                        deleted_count += 1
                        
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] GCS Cleanup: Deleted {deleted_count} blobs older than 24h.")
        except Exception as e:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] GCS Cleanup Error: {e}")
            
        # Sleep for exactly 24 hours (24 * 3600 seconds)
        time.sleep(24 * 3600)

def poll_batch_job(client: genai.Client, job_name: str) -> str:
    """Polls the status of an active Vertex AI batch prediction job until it terminates."""
    return ai.poll_batch_job(client, job_name, interval_sec=60)

def download_and_parse_output(dest_uri: str) -> str:
    """Downloads prediction results from GCS and returns the extracted AI summary text."""
    return ai.download_and_parse_output(dest_uri, BUCKET_NAME, PROJECT_ID)

def run_batch_cycle(client: genai.Client) -> None:
    """Triggers a single Batch Prediction pipeline run from input to cached output.

    Builds telemetry summaries, constructs the multi-item payload manifest, uploads to GCS,
    submits the batch job, polls until completion, parses the results, updates the cache,
    and handles exceptions cleanly.

    Args:
        client: The initialized Google GenAI SDK Client object.

    Returns:
        None

    Raises:
        None
    """
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Triggering new Batch prediction cycle...")
    
    # 1. Assemble prompt data
    csv_data: str = generate_hourly_summaries()
    if not csv_data:
        print("No telemetry data to aggregate. Skipping cycle.")
        return
        
    prompt_path: str = os.path.join(SCRIPT_DIR, "gemini_prompt.txt")
    if not os.path.exists(prompt_path):
        print(f"ERROR: Prompt template not found at {prompt_path}")
        return
        
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template: str = f.read()
        
    now: datetime.datetime = datetime.datetime.now()
    current_dt_str: str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    csv_lines: List[str] = csv_data.split("\n")
    first_dt_str: str = csv_lines[1].split(",")[0] if len(csv_lines) > 1 else "N/A"
    last_dt_str: str = csv_lines[-1].split(",")[0] if len(csv_lines) > 1 else "N/A"
    
    try:
        formatted_prompt: str = prompt_template.format(
            csv_data=csv_data,
            current_date_time=current_dt_str,
            last_data_time=last_dt_str,
            first_data_time=first_dt_str
        )
    except Exception as e:
        print(f"Error formatting prompt: {e}")
        return
        
    # 2. Package manifest (bundle with 14 duplicate queries to satisfy the 15-request floor)
    prompts: List[Dict[str, Any]] = []
    timestamp_sec: int = int(time.time())
    for idx in range(15):
        prompts.append({
            "request_id": f"power_meter_query_{idx:03d}_{timestamp_sec}",
            "request": {
                "contents": [{"role": "user", "parts": [{"text": formatted_prompt}]}],
                "systemInstruction": {"parts": [{"text": "You are a precise grid monitor summarizer."}]}
            }
        })
        
    local_path: str = f"staging_request_{timestamp_sec}.jsonl"
    with open(local_path, "w", encoding="utf-8") as f:
        for p in prompts:
            f.write(json.dumps(p) + "\n")
            
    # 3. Upload and trigger job
    gcs_input_path: str = f"dashboard_emulation/stage_input_{timestamp_sec}.jsonl"
    dest_uri: str = f"gs://{BUCKET_NAME}/dashboard_emulation_output/stage_output_{timestamp_sec}/"
    
    try:
        # Resilient GCS Upload with retries
        gcs_uri: str = ""
        for attempt in range(3):
            try:
                gcs_uri = upload_to_gcs(local_path, gcs_input_path)
                print(f"Uploaded input manifest to {gcs_uri}")
                break
            except Exception as upload_err:
                if attempt == 2:
                    raise upload_err
                print(f"GCS Upload failed: {upload_err}. Retrying in 10s...")
                time.sleep(10)
                
        # Resilient Vertex Batch Job creation with retries
        batch_job: Any = None
        for attempt in range(3):
            try:
                batch_job = client.batches.create(
                    model=MODEL_NAME,
                    src=gcs_uri,
                    config={'dest': dest_uri}
                )
                break
            except Exception as create_err:
                if attempt == 2:
                    raise create_err
                print(f"Vertex job creation failed: {create_err}. Retrying in 10s...")
                time.sleep(10)
                
        print(f"Submitted Batch Job successfully: {batch_job.name}")
        
        # Write watchdog state file to survive reboots/unexpected terminations
        state_payload = {
            "job_name": batch_job.name,
            "dest_uri": dest_uri,
            "timestamp": current_dt_str
        }
        with open(ACTIVE_BATCH_STATE, "w", encoding="utf-8") as sf:
            json.dump(state_payload, sf, indent=4)
        print(f"Saved active job watchdog details to {ACTIVE_BATCH_STATE}")
        
        if os.path.exists(local_path):
            os.remove(local_path)
            
        # 4. Wait for processing, parse result, and update local cache
        status: str = poll_batch_job(client, batch_job.name)
        if status == "SUCCEEDED":
            summary: str = ""
            # Resilient result download with retries
            for attempt in range(5):
                summary = download_and_parse_output(dest_uri)
                if summary:
                    break
                print(f"Failed to retrieve summary from GCS. Retrying download in 30s...")
                time.sleep(30)
                
            if summary:
                retrieved_dt_str: str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                summary_with_metadata: str = f"{summary}\n\n[Batch Submitted: {current_dt_str} | Retrieved: {retrieved_dt_str}]"
                # Resilient cache merge to avoid overwriting background DFT spectrum and metrics
                cache_payload: Dict[str, Any] = {}
                if os.path.exists(GEMINI_SUMMARY_CACHE):
                    try:
                        from dashboard_modules import io as modular_io
                        cache_payload = modular_io.read_safe_json(GEMINI_SUMMARY_CACHE) or {}
                    except Exception as merge_err:
                        print(f"Merge warning: could not load existing cache: {merge_err}")
                
                cache_payload["timestamp"] = current_dt_str
                cache_payload["summary"] = summary_with_metadata
                with open(GEMINI_SUMMARY_CACHE, "w", encoding="utf-8") as cache_file:
                    json.dump(cache_payload, cache_file, indent=4)
                print(f"🎉 SUCCESS: Cached fresh summary to {GEMINI_SUMMARY_CACHE}")
                # Clean up watchdog file only after successful download
                if os.path.exists(ACTIVE_BATCH_STATE):
                    os.remove(ACTIVE_BATCH_STATE)
            else:
                print("Error: Could not retrieve summary text from predictions file after multiple retries. Keeping watchdog active.")
        else:
            print("ERROR: Batch Prediction job failed. Cleaning up watchdog.")
            if os.path.exists(ACTIVE_BATCH_STATE):
                os.remove(ACTIVE_BATCH_STATE)
            
    except Exception as e:
        print(f"Exception during batch run cycle: {e}")
        if os.path.exists(local_path):
            os.remove(local_path)

def main() -> None:
    """Main execution orchestrator for the background staging service.

    Configures credentials, kicks off the cleanup loop, initializes the GenAI
    client, and runs the 30-minute interval polling cycle.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    setup_credentials()
    
    # Run the GCS cleanup routine as a background daemon thread
    cleanup_thread: threading.Thread = threading.Thread(target=gcs_cleanup_loop, daemon=True)
    cleanup_thread.start()
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Started background GCS cleanup thread.")
    
    client: genai.Client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    # Primary runner loop checking cache age periodically
    while True:
        sleep_seconds = BATCH_INTERVAL_HOURS * 3600
        try:
            # First, check if there is an in-flight job from a previous run (watchdog check)
            if os.path.exists(ACTIVE_BATCH_STATE):
                try:
                    with open(ACTIVE_BATCH_STATE, "r") as sf:
                        job_state = json.load(sf)
                    job_name = job_state.get("job_name")
                    dest_uri = job_state.get("dest_uri")
                    ts_str = job_state.get("timestamp")
                    
                    if job_name and dest_uri and ts_str:
                        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Watchdog: Found in-flight job {job_name} from {ts_str}. Resuming poll...")
                        status = poll_batch_job(client, job_name)
                        if status == "SUCCEEDED":
                            summary = download_and_parse_output(dest_uri)
                            if summary:
                                resumed_retrieved_dt_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                summary_with_metadata = f"{summary}\n\n[Batch Submitted: {ts_str} | Retrieved: {resumed_retrieved_dt_str}]"
                                # Resilient cache merge to avoid overwriting background DFT spectrum and metrics
                                cache_payload: Dict[str, Any] = {}
                                if os.path.exists(GEMINI_SUMMARY_CACHE):
                                    try:
                                        from dashboard_modules import io as modular_io
                                        cache_payload = modular_io.read_safe_json(GEMINI_SUMMARY_CACHE) or {}
                                    except Exception as merge_err:
                                        print(f"Merge warning: could not load existing cache: {merge_err}")
                                
                                cache_payload["timestamp"] = ts_str
                                cache_payload["summary"] = summary_with_metadata
                                with open(GEMINI_SUMMARY_CACHE, "w", encoding="utf-8") as cache_file:
                                    json.dump(cache_payload, cache_file, indent=4)
                                print(f"🎉 SUCCESS: Cached resumed summary to {GEMINI_SUMMARY_CACHE}")
                            else:
                                print("Error: Could not retrieve summary text from predictions file.")
                        else:
                            print("ERROR: Resumed Batch Prediction job failed.")
                            
                        # Remove watchdog state file
                        if os.path.exists(ACTIVE_BATCH_STATE):
                            os.remove(ACTIVE_BATCH_STATE)
                except Exception as watchdog_err:
                    print(f"Error resuming from watchdog state: {watchdog_err}")
                    if os.path.exists(ACTIVE_BATCH_STATE):
                        os.remove(ACTIVE_BATCH_STATE)
            
            is_cache_fresh: bool = False
            if os.path.exists(GEMINI_SUMMARY_CACHE):
                try:
                    with open(GEMINI_SUMMARY_CACHE, "r") as f:
                        cache_data: Dict[str, Any] = json.load(f)
                    ts_str = cache_data.get("timestamp")
                    if ts_str:
                        cache_time: Optional[datetime.datetime] = None
                        try:
                            cache_time = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            try:
                                cache_time = datetime.datetime.fromisoformat(ts_str)
                            except ValueError:
                                cache_time = datetime.datetime.strptime(ts_str.split(".")[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                                
                        if cache_time:
                            elapsed_sec = (datetime.datetime.now() - cache_time).total_seconds()
                            if elapsed_sec < BATCH_INTERVAL_HOURS * 3600:
                                is_cache_fresh = True
                                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Local cache is still fresh (< {BATCH_INTERVAL_HOURS}h). Skipping run.")
                                remaining_sec = (BATCH_INTERVAL_HOURS * 3600) - elapsed_sec
                                # Add 60s buffer to ensure expiration has occurred when waking up
                                sleep_seconds = int(max(remaining_sec + 60, 60))
                except Exception as e:
                    print(f"Failed to check cache state: {e}")
            
            if not is_cache_fresh:
                run_batch_cycle(client)
                
        except Exception as e:
            print(f"Loop Exception: {e}")
            
        if sleep_seconds >= 3600:
            h_val = sleep_seconds / 3600.0
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Sleeping for {h_val:.2f} hours...")
        else:
            m_val = sleep_seconds / 60.0
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Sleeping for {m_val:.1f} minutes...")
        time.sleep(sleep_seconds)

if __name__ == "__main__":
    main()

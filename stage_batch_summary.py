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

# -------------------------------------------------------------
# Configuration Constants (Pulling from Environment/Defaults)
# -------------------------------------------------------------
LOCATION: str = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
MODEL_NAME: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
BUCKET_NAME: str = os.environ.get("GEMINI_BATCH_BUCKET", "mutua-477100-batch-images")
PROJECT_ID: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "mutua-477100")

# Path configuration relative to script directory to ensure portability
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
GEMINI_SUMMARY_CACHE: str = os.path.join(SCRIPT_DIR, "gemini_summary.json")
ACTIVE_BATCH_STATE: str = os.path.join(SCRIPT_DIR, "active_batch_job.json")

# Local Telemetry CSV History Paths (Matching dashboard.py dynamic resolver)
HOME_DIR: str = os.path.expanduser("~")
LOCAL_GRID: str = os.path.join(SCRIPT_DIR, "grid_history.csv")
GRID_HISTORY: str = LOCAL_GRID if os.path.exists(LOCAL_GRID) else os.path.join(HOME_DIR, "grid_history.csv")

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
    if not os.path.exists(GRID_HISTORY):
        print(f"Warning: {GRID_HISTORY} not found.")
        return ""
        
    hourly_data: Dict[str, List[float]] = defaultdict(list)
    try:
        with open(GRID_HISTORY, 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) == 2:
                    ts_str: str = row[0].strip().replace('\x00', '')
                    val_str: str = row[1].strip().replace('\x00', '')
                    if not ts_str or not val_str:
                        continue
                    # Extracts the 'YYYY-MM-DD HH' prefix for easy alignment
                    hour_key: str = ts_str[:13].replace('T', ' ') + ":00"
                    try:
                        hourly_data[hour_key].append(float(val_str))
                    except ValueError:
                        continue
    except Exception as e:
        print(f"Error parsing grid history: {e}")
        return ""
        
    se_hourly_data: Dict[str, List[float]] = defaultdict(list)
    if os.path.exists(SE_HISTORY):
        try:
            with open(SE_HISTORY, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 2:
                        ts_str = row[0].strip().replace('\x00', '')
                        val_str = row[1].strip().replace('\x00', '')
                        if not ts_str or not val_str:
                            continue
                        hour_key = ts_str[:13].replace('T', ' ') + ":00"
                        try:
                            se_hourly_data[hour_key].append(float(val_str))
                        except ValueError:
                            continue
        except Exception as e:
            print(f"Error parsing SolarEdge history: {e}")
            
    se_battery_hourly_data: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    if os.path.exists(SE_BATTERY_HISTORY):
        try:
            with open(SE_BATTERY_HISTORY, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 3:
                        ts_str = row[0].strip().replace('\x00', '')
                        p_str: str = row[1].strip().replace('\x00', '')
                        soc_str: str = row[2].strip().replace('\x00', '')
                        if not ts_str or not p_str or not soc_str:
                            continue
                        hour_key = ts_str[:13].replace('T', ' ') + ":00"
                        try:
                            se_battery_hourly_data[hour_key].append((float(p_str), float(soc_str)))
                        except ValueError:
                            continue
        except Exception as e:
            print(f"Error parsing SolarEdge battery history: {e}")
            
    chilicon_hourly_data: Dict[str, List[float]] = defaultdict(list)
    if os.path.exists(CHILICON_HISTORY):
        try:
            with open(CHILICON_HISTORY, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 3:
                        ts_str = row[0].strip().replace('\x00', '')
                        p_str = row[1].strip().replace('\x00', '')
                        if not ts_str or not p_str:
                            continue
                        hour_key = ts_str[:13].replace('T', ' ') + ":00"
                        try:
                            chilicon_hourly_data[hour_key].append(float(p_str))
                        except ValueError:
                            continue
        except Exception as e:
            print(f"Error parsing Chillicon history: {e}")

    lines: List[str] = ["Hour,Avg_kW,Min_kW,Max_kW,Median_kW,SE_Avg_kW,SE_Max_kW,SE_Energy_kWh,Battery_Avg_kW,Battery_SoC,Chillicon_Avg_kW,Chillicon_Max_kW,Chillicon_Energy_kWh"]
    all_hours: List[str] = sorted(list(set(
        list(hourly_data.keys()) + 
        list(se_hourly_data.keys()) + 
        list(se_battery_hourly_data.keys()) + 
        list(chilicon_hourly_data.keys())
    )))
    
    for hour in all_hours:
        vals: List[float] = hourly_data[hour]
        se_vals: List[float] = se_hourly_data[hour]
        bat_vals: List[Tuple[float, float]] = se_battery_hourly_data[hour]
        ch_vals: List[float] = chilicon_hourly_data[hour]
        
        avg_kw: float = 0.0
        min_kw: float = 0.0
        max_kw: float = 0.0
        med_kw: float = 0.0
        if vals:
            avg_kw = sum(vals) / len(vals)
            min_kw = min(vals)
            max_kw = max(vals)
            med_kw = statistics.median(vals)
            
        se_avg_kw: float = 0.0
        se_max_kw: float = 0.0
        se_energy_kwh: float = 0.0
        if se_vals:
            se_avg_kw = sum(se_vals) / len(se_vals)
            se_max_kw = max(se_vals)
            se_energy_kwh = se_avg_kw * 1.0 # 1 hour integration approximation
            
        bat_avg_kw: float = 0.0
        bat_avg_soc: float = 0.0
        if bat_vals:
            bat_powers: List[float] = [v[0] for v in bat_vals]
            bat_socs: List[float] = [v[1] for v in bat_vals]
            bat_avg_kw = sum(bat_powers) / len(bat_powers)
            bat_avg_soc = sum(bat_socs) / len(bat_socs)
            
        ch_avg_kw: float = 0.0
        ch_max_kw: float = 0.0
        ch_energy_kwh: float = 0.0
        if ch_vals:
            ch_avg_kw = sum(ch_vals) / len(ch_vals)
            ch_max_kw = max(ch_vals)
            ch_energy_kwh = ch_avg_kw * 1.0
            
        lines.append(f"{hour},{avg_kw:.3f},{min_kw:.3f},{max_kw:.3f},{med_kw:.3f},{se_avg_kw:.3f},{se_max_kw:.3f},{se_energy_kwh:.3f},{bat_avg_kw:.3f},{bat_avg_soc:.1f},{ch_avg_kw:.3f},{ch_max_kw:.3f},{ch_energy_kwh:.3f}")
        
    return "\n".join(lines)

def upload_to_gcs(local_path: str, gcs_path: str) -> str:
    """Uploads a local manifest or configuration file to Google Cloud Storage.

    Args:
        local_path: Absolute filesystem path to the file to upload.
        gcs_path: The target GCS destination blob object key.

    Returns:
        The full GCS URI string (e.g. 'gs://bucket-name/path/file.ext').

    Raises:
        GoogleCloudError: If the upload operation encounters GCP network or IAM errors.
    """
    storage_client: storage.Client = storage.Client(project=PROJECT_ID)
    bucket: storage.Bucket = storage_client.bucket(BUCKET_NAME)
    blob: storage.Blob = bucket.blob(gcs_path)
    blob.upload_from_filename(local_path)
    return f"gs://{BUCKET_NAME}/{gcs_path}"

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
            storage_client: storage.Client = storage.Client(project=PROJECT_ID)
            bucket: storage.Bucket = storage_client.bucket(BUCKET_NAME)
            now_utc: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
            cutoff: datetime.datetime = now_utc - datetime.timedelta(hours=24)
            
            deleted_count: int = 0
            for prefix in ["dashboard_emulation/", "dashboard_emulation_output/"]:
                blobs: List[storage.Blob] = list(bucket.list_blobs(prefix=prefix))
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
    """Polls the status of an active Vertex AI batch prediction job until it terminates.

    Args:
        client: The initialized Google GenAI SDK Client object.
        job_name: The resource locator name of the batch job.

    Returns:
        A string representing the final job state ('SUCCEEDED' or 'FAILED').

    Raises:
        None
    """
    while True:
        try:
            job: Any = client.batches.get(name=job_name)
            state_str: str = str(job.state).split(".")[-1]
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Job State: {state_str}")
            if "SUCCEEDED" in state_str:
                return "SUCCEEDED"
            elif "FAILED" in state_str:
                return "FAILED"
        except Exception as e:
            print(f"Error checking job status: {e}")
        time.sleep(60)

def download_and_parse_output(dest_uri: str) -> str:
    """Downloads prediction results from GCS and returns the extracted AI summary text.

    Args:
        dest_uri: The destination GCS directory URI.

    Returns:
        The decoded summary string text if successful; empty string on failure.

    Raises:
        None
    """
    try:
        storage_client: storage.Client = storage.Client(project=PROJECT_ID)
        bucket: storage.Bucket = storage_client.bucket(BUCKET_NAME)
        
        # Parse the relative path from GCS URI
        prefix: str = dest_uri.replace(f"gs://{BUCKET_NAME}/", "")
        
        blobs: List[storage.Blob] = list(bucket.list_blobs(prefix=prefix))
        for blob in blobs:
            if blob.name.endswith("predictions.jsonl"):
                content: str = blob.download_as_text()
                lines: List[str] = content.strip().split("\n")
                for line in lines:
                    if not line:
                        continue
                    data: Dict[str, Any] = json.loads(line)
                    # We only parse the response matching our target index (query_000)
                    if data.get("request_id", "").startswith("power_meter_query_000_"):
                        if "response" in data and "candidates" in data["response"]:
                            parts: List[Dict[str, Any]] = data["response"]["candidates"][0]["content"]["parts"]
                            return parts[0].get("text", "").strip()
    except Exception as e:
        print(f"Error downloading or parsing output: {e}")
    return ""

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
                cache_payload: Dict[str, str] = {
                    "timestamp": current_dt_str,
                    "summary": summary_with_metadata
                }
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
    
    # Primary runner loop checking cache age every 30 minutes
    while True:
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
                                cache_payload = {
                                    "timestamp": ts_str,
                                    "summary": summary_with_metadata
                                }
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
                                
                        if cache_time and (datetime.datetime.now() - cache_time < datetime.timedelta(minutes=30)):
                            is_cache_fresh = True
                            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Local cache is still fresh (< 30m). Skipping run.")
                except Exception as e:
                    print(f"Failed to check cache state: {e}")
            
            if not is_cache_fresh:
                run_batch_cycle(client)
                
        except Exception as e:
            print(f"Loop Exception: {e}")
            
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Sleeping for 30 minutes...")
        time.sleep(30 * 60)

if __name__ == "__main__":
    main()

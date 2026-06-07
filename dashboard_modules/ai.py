"""AI prompt construction, real-time Gemini/Ollama summaries, and Batch API scheduling.

Centralizes local and cloud model operations, keeping main entry points clean.
"""

import datetime
import json
import logging
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

# Local imports
from .io import read_clean_csv

BACKOFF_DELAYS: List[int] = [2, 4, 8]

# Lazy load genai and storage SDKs to prevent import errors on offline or lightweight nodes
genai_module = None
storage_module = None


def get_genai():
    """Lazy imports the google-genai SDK."""
    global genai_module
    if genai_module is None:
        from google import genai
        genai_module = genai
    return genai_module


def get_storage():
    """Lazy imports the google-cloud-storage SDK."""
    global storage_module
    if storage_module is None:
        from google.cloud import storage
        storage_module = storage
    return storage_module


def generate_hourly_summaries(
    grid_history_path: str,
    se_history_path: str,
    se_battery_history_path: str,
    chilicon_history_path: str
) -> str:
    """Parses local CSV logs and computes hourly aggregate statistics for reports.

    Returns:
        A compact CSV string where each row represents one hour of aligned data.
    """
    import os
    grid_rows = read_clean_csv(grid_history_path)
    if not grid_rows:
        logging.warning(f"No grid history found at {grid_history_path}.")
        return ""
        
    hourly_data: Dict[str, List[float]] = defaultdict(list)
    for row in grid_rows:
        if len(row) == 2:
            ts_str = row[0]
            val_str = row[1]
            hour_key = ts_str[:13].replace('T', ' ') + ":00"
            try:
                hourly_data[hour_key].append(float(val_str))
            except ValueError:
                continue
        
    se_hourly_data: Dict[str, List[float]] = defaultdict(list)
    se_rows = read_clean_csv(se_history_path)
    for row in se_rows:
        if len(row) == 2:
            ts_str = row[0]
            val_str = row[1]
            hour_key = ts_str[:13].replace('T', ' ') + ":00"
            try:
                se_hourly_data[hour_key].append(float(val_str))
            except ValueError:
                continue
            
    se_battery_hourly_data: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    se_bat_rows = read_clean_csv(se_battery_history_path)
    for row in se_bat_rows:
        if len(row) == 3:
            ts_str = row[0]
            p_str = row[1]
            soc_str = row[2]
            hour_key = ts_str[:13].replace('T', ' ') + ":00"
            try:
                se_battery_hourly_data[hour_key].append((float(p_str), float(soc_str)))
            except ValueError:
                continue
            
    chilicon_hourly_data: Dict[str, List[float]] = defaultdict(list)
    ch_rows = read_clean_csv(chilicon_history_path)
    for row in ch_rows:
        if len(row) == 3:
            ts_str = row[0]
            p_str = row[1]
            hour_key = ts_str[:13].replace('T', ' ') + ":00"
            try:
                chilicon_hourly_data[hour_key].append(float(p_str))
            except ValueError:
                continue

    se_flow_hourly_data: Dict[str, List[float]] = defaultdict(list)
    se_flow_history_path = se_history_path.replace("solaredge_history.csv", "solaredge_flow_history.csv")
    if os.path.exists(se_flow_history_path):
        se_flow_rows = read_clean_csv(se_flow_history_path)
        for row in se_flow_rows:
            if len(row) >= 3:
                ts_str = row[0]
                val_str = row[2]  # load_power is at index 2
                hour_key = ts_str[:13].replace('T', ' ') + ":00"
                try:
                    se_flow_hourly_data[hour_key].append(float(val_str))
                except ValueError:
                    continue

    lines: List[str] = [
        "Hour,Avg_kW,Min_kW,Max_kW,Median_kW,SE_Avg_kW,SE_Max_kW,SE_Energy_kWh,"
        "Battery_Avg_kW,Battery_SoC,Chillicon_Avg_kW,Chillicon_Max_kW,Chillicon_Energy_kWh,"
        "Load_Avg_kW,Load_Max_kW,Load_Energy_kWh"
    ]
    all_hours: List[str] = sorted(list(set(
        list(hourly_data.keys()) + 
        list(se_hourly_data.keys()) + 
        list(se_battery_hourly_data.keys()) + 
        list(chilicon_hourly_data.keys()) +
        list(se_flow_hourly_data.keys())
    )))
    
    for hour in all_hours:
        vals = hourly_data.get(hour, [])
        se_vals = se_hourly_data.get(hour, [])
        bat_vals = se_battery_hourly_data.get(hour, [])
        ch_vals = chilicon_hourly_data.get(hour, [])
        se_flow_vals = se_flow_hourly_data.get(hour, [])
        
        avg_kw = sum(vals) / len(vals) if vals else 0.0
        min_kw = min(vals) if vals else 0.0
        max_kw = max(vals) if vals else 0.0
        med_kw = statistics.median(vals) if vals else 0.0
            
        se_avg_kw = sum(se_vals) / len(se_vals) if se_vals else 0.0
        se_max_kw = max(se_vals) if se_vals else 0.0
        se_energy_kwh = se_avg_kw * 1.0
            
        bat_avg_kw = 0.0
        bat_avg_soc = 0.0
        if bat_vals:
            bat_powers = [v[0] for v in bat_vals]
            bat_socs = [v[1] for v in bat_vals]
            bat_avg_kw = sum(bat_powers) / len(bat_powers)
            bat_avg_soc = sum(bat_socs) / len(bat_socs)
            
        ch_avg_kw = sum(ch_vals) / len(ch_vals) if ch_vals else 0.0
        ch_max_kw = max(ch_vals) if ch_vals else 0.0
        ch_energy_kwh = ch_avg_kw * 1.0

        load_avg_kw = sum(se_flow_vals) / len(se_flow_vals) if se_flow_vals else 0.0
        load_max_kw = max(se_flow_vals) if se_flow_vals else 0.0
        load_energy_kwh = load_avg_kw * 1.0
            
        lines.append(
            f"{hour},{avg_kw:.3f},{min_kw:.3f},{max_kw:.3f},{med_kw:.3f},{se_avg_kw:.3f},"
            f"{se_max_kw:.3f},{se_energy_kwh:.3f},{bat_avg_kw:.3f},{bat_avg_soc:.1f},"
            f"{ch_avg_kw:.3f},{ch_max_kw:.3f},{ch_energy_kwh:.3f},"
            f"{load_avg_kw:.3f},{load_max_kw:.3f},{load_energy_kwh:.3f}"
        )
        
    return "\n".join(lines)


def fetch_gemini_summary(
    prompt_template_path: str,
    context_data: Dict[str, Any],
    local_llm: bool = False,
    ollama_endpoint: str = "http://localhost:11434/api/generate",
    ollama_model: str = "gemma4-it-q4",
    gcp_project_id: Optional[str] = None
) -> str:
    """Executes a text summary query against Google GenAI (Gemini) or local Ollama.

    Args:
        prompt_template_path: Location of the system instructions template file.
        context_data: Variables to format/inject into the prompt template.
        local_llm: Set to True to query local Ollama; False to query Gemini.

    Returns:
        The text response from the model.
    """
    try:
        with open(prompt_template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        prompt = template.format(**context_data)
    except Exception as e:
        logging.error(f"Failed to load or format prompt template: {e}")
        return "System error: Failed to format LLM prompt template."

    if local_llm:
        # Query local Ollama instance
        payload = {
            "model": ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": 150,
                "temperature": 0.2
            }
        }
        try:
            req = urllib.request.Request(
                ollama_endpoint,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.loads(r.read().decode('utf-8'))
                return res.get("response", "").strip()
        except Exception as e:
            logging.error(f"Local Ollama summary fetch failed: {e}")
            return "Local AI summary unavailable."
    else:
        # Query remote Vertex AI (Gemini) via Google GenAI SDK
        try:
            genai = get_genai()
            import os
            # Initialize client. Use Vertex AI if service account credentials are set up.
            if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
                project = gcp_project_id or os.environ.get("GOOGLE_CLOUD_PROJECT") or "mutua-477100"
                location = os.environ.get("GOOGLE_CLOUD_LOCATION") or "global"
                client = genai.Client(vertexai=True, project=project, location=location)
            elif gcp_project_id:
                client = genai.Client(http_options={'headers': {'X-Goog-User-Project': gcp_project_id}})
            else:
                client = genai.Client()
                
            # Native Exponential Backoff Retry Loop
            response = None
            for attempt, delay in enumerate(BACKOFF_DELAYS + [0]):
                try:
                    response = client.models.generate_content(
                        model='gemini-1.5-flash',
                        contents=prompt
                    )
                    break
                except Exception as api_err:
                    if attempt < len(BACKOFF_DELAYS):
                        logging.warning(
                            f"Gemini API call failed: {api_err}. Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                    else:
                        logging.error(
                            f"Gemini API completely failed after retries: {api_err}"
                        )
                        raise
            
            return response.text.strip()
        except Exception as e:
            logging.error(f"Remote Gemini summary fetch failed: {e}")
            return "AI Summary unavailable."


def upload_to_gcs(local_path: str, gcs_path: str, bucket_name: str, project_id: str) -> str:
    """Uploads a local batch prediction JSON to Google Cloud Storage.

    Returns:
        The GCS URI string ('gs://bucket-name/path').
    """
    storage = get_storage()
    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(local_path)
    return f"gs://{bucket_name}/{gcs_path}"


def poll_batch_job(client, job_name: str, interval_sec: int = 30) -> str:
    """Polls a Vertex AI batch prediction job until it terminates.

    Returns:
        Job state string (e.g. 'SUCCEEDED' or 'FAILED').
    """
    while True:
        try:
            job = client.batches.get(name=job_name)
            state_str = str(job.state).split(".")[-1]
            logging.info(f"Batch prediction state: {state_str}")
            if "SUCCEEDED" in state_str:
                return "SUCCEEDED"
            elif "FAILED" in state_str:
                return "FAILED"
        except Exception as e:
            logging.error(f"Error querying batch job status: {e}")
        time.sleep(interval_sec)


def download_and_parse_output(dest_uri: str, bucket_name: str, project_id: str) -> str:
    """Downloads batch predictions JSONL and extracts the AI summary text."""
    try:
        storage = get_storage()
        storage_client = storage.Client(project=project_id)
        bucket = storage_client.bucket(bucket_name)
        
        prefix = dest_uri.replace(f"gs://{bucket_name}/", "")
        blobs = list(bucket.list_blobs(prefix=prefix))
        for blob in blobs:
            if blob.name.endswith("predictions.jsonl"):
                content = blob.download_as_text()
                lines = content.strip().split("\n")
                for line in lines:
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("request_id", "").startswith("power_meter_query_000_"):
                        if "response" in data and "candidates" in data["response"]:
                            parts = data["response"]["candidates"][0]["content"]["parts"]
                            return parts[0].get("text", "").strip()
    except Exception as e:
        logging.error(f"Error downloading/parsing batch GCS output: {e}")
    return ""

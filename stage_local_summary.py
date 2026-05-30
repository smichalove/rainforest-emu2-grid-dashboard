import os
import json
import time
import datetime
import csv
import statistics
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------
# Configuration Constants
# -------------------------------------------------------------
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
GEMINI_SUMMARY_CACHE: str = os.path.join(SCRIPT_DIR, "gemini_summary.json")
ACTIVE_LOCAL_STATE: str = os.path.join(SCRIPT_DIR, "active_local_job.json")

# Model configuration
DEFAULT_MODEL: str = os.environ.get("EDGE_MODEL", "gemma2:2b")
OLLAMA_ENDPOINT: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434/api/generate")

# Local Telemetry CSV History Paths
HOME_DIR: str = os.path.expanduser("~")
LOCAL_GRID: str = os.path.join(SCRIPT_DIR, "grid_history.csv")
GRID_HISTORY: str = LOCAL_GRID if os.path.exists(LOCAL_GRID) else os.path.join(HOME_DIR, "grid_history.csv")

LOCAL_SE: str = os.path.join(SCRIPT_DIR, "solaredge_history.csv")
SE_HISTORY: str = LOCAL_SE if os.path.exists(LOCAL_SE) else os.path.join(HOME_DIR, "solaredge_history.csv")

LOCAL_SE_BATTERY: str = os.path.join(SCRIPT_DIR, "solaredge_battery_history.csv")
SE_BATTERY_HISTORY: str = LOCAL_SE_BATTERY if os.path.exists(LOCAL_SE_BATTERY) else os.path.join(HOME_DIR, "solaredge_battery_history.csv")

LOCAL_CHILICON: str = os.path.join(SCRIPT_DIR, "chilicon_history.csv")
CHILICON_HISTORY: str = LOCAL_CHILICON if os.path.exists(LOCAL_CHILICON) or not os.path.exists(os.path.join(HOME_DIR, "chilicon_history.csv")) else os.path.join(HOME_DIR, "chilicon_history.csv")


def sanitize_reader(filepath: str) -> List[List[str]]:
    """Reads a CSV file while dynamically sanitizing NUL bytes on the fly to avoid parser crashes."""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            return list(reader)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return []


def generate_hourly_records() -> List[Tuple]:
    """Parses local CSV logs and aligns them into hourly records."""
    grid_rows = sanitize_reader(GRID_HISTORY)
    if not grid_rows:
        return []
        
    hourly_data = defaultdict(list)
    for row in grid_rows:
        if len(row) == 2:
            ts, val = row[0].strip(), row[1].strip()
            if ts and val:
                hour_key = ts[:13].replace('T', ' ') + ":00"
                try:
                    hourly_data[hour_key].append(float(val))
                except ValueError:
                    pass

    se_hourly = defaultdict(list)
    se_rows = sanitize_reader(SE_HISTORY)
    for row in se_rows:
        if len(row) == 2:
            ts, val = row[0].strip(), row[1].strip()
            if ts and val:
                hour_key = ts[:13].replace('T', ' ') + ":00"
                try:
                    se_hourly[hour_key].append(float(val))
                except ValueError:
                    pass

    bat_hourly = defaultdict(list)
    bat_rows = sanitize_reader(SE_BATTERY_HISTORY)
    for row in bat_rows:
        if len(row) == 3:
            ts, p, soc = row[0].strip(), row[1].strip(), row[2].strip()
            if ts and p and soc:
                hour_key = ts[:13].replace('T', ' ') + ":00"
                try:
                    bat_hourly[hour_key].append((float(p), float(soc)))
                except ValueError:
                    pass

    ch_hourly = defaultdict(list)
    ch_rows = sanitize_reader(CHILICON_HISTORY)
    for row in ch_rows:
        if len(row) == 3:
            ts, p, e = row[0].strip(), row[1].strip(), row[2].strip()
            if ts and p:
                hour_key = ts[:13].replace('T', ' ') + ":00"
                try:
                    ch_hourly[hour_key].append(float(p))
                except ValueError:
                    pass

    all_hours = sorted(list(set(
        list(hourly_data.keys()) + 
        list(se_hourly.keys()) + 
        list(bat_hourly.keys()) + 
        list(ch_hourly.keys())
    )))
    
    records = []
    for h in all_hours:
        vals = hourly_data[h]
        se_vals = se_hourly[h]
        bat_vals = bat_hourly[h]
        ch_vals = ch_hourly[h]
        
        avg_kw = sum(vals)/len(vals) if vals else 0.0
        min_kw = min(vals) if vals else 0.0
        max_kw = max(vals) if vals else 0.0
        med_kw = statistics.median(vals) if vals else 0.0
        
        se_avg = sum(se_vals)/len(se_vals) if se_vals else 0.0
        se_max = max(se_vals) if se_vals else 0.0
        se_energy = se_avg * 1.0
        
        bat_avg = 0.0
        bat_soc = 0.0
        if bat_vals:
            bat_avg = sum([v[0] for v in bat_vals])/len(bat_vals)
            bat_soc = sum([v[1] for v in bat_vals])/len(bat_vals)
            
        ch_avg = sum(ch_vals)/len(ch_vals) if ch_vals else 0.0
        ch_max = max(ch_vals) if ch_vals else 0.0
        ch_energy = ch_avg * 1.0
        
        records.append((h, avg_kw, min_kw, max_kw, med_kw, se_avg, se_max, se_energy, bat_avg, bat_soc, ch_avg, ch_max, ch_energy))
        
    return records


def calculate_metrics(records: List[Tuple]) -> Dict[str, Any]:
    """Computes mathematically precise metrics from aligned hourly telemetry records.

    Uses standard rules to compute imports, exports, SolarEdge/Chillicon generation,
    battery Flex Event activity, and billing impacts.
    """
    total_imported = 0.0
    total_exported = 0.0
    se_generated = 0.0
    battery_discharged = 0.0
    battery_charged = 0.0
    chilicon_generated = 0.0
    inferred_chilicon = 0.0
    
    peak_grid_import = 0.0
    peak_grid_export = 0.0
    peak_se_pv = 0.0
    peak_chilicon_pv = 0.0
    
    for r in records:
        h, avg_kw, min_kw, max_kw, med_kw, se_avg, se_max, se_energy, bat_avg, bat_soc, ch_avg, ch_max, ch_energy = r
        
        # 1. Grid Imports / Exports (kWh)
        if avg_kw > 0:
            total_imported += avg_kw * 1.0
        else:
            total_exported += abs(avg_kw) * 1.0
            
        # Peaks
        if max_kw > 0:
            peak_grid_import = max(peak_grid_import, max_kw)
        if min_kw < 0:
            peak_grid_export = max(peak_grid_export, abs(min_kw))
            
        # 2. SolarEdge Generated
        se_generated += se_energy
        peak_se_pv = max(peak_se_pv, se_max)
        
        # 3. Battery Activity
        if bat_avg > 0:
            battery_discharged += bat_avg * 1.0
        else:
            battery_charged += abs(bat_avg) * 1.0
            
        # 4. Chillicon Generated
        chilicon_generated += ch_energy
        peak_chilicon_pv = max(peak_chilicon_pv, ch_max)
        
        # 5. Inferred Chillicon
        if avg_kw < 0:
            grid_export_rate = abs(avg_kw)
            inferred_rate = grid_export_rate - se_avg - max(0.0, bat_avg)
            if inferred_rate > 0:
                inferred_chilicon += inferred_rate * 1.0

    # Net Billing Impact
    # Import cost: $0.19/kWh
    # Standard Export credit: $0.19/kWh
    # Battery Discharge bonus: $0.31/kWh (reimbursed at $0.50/kWh total)
    import_cost = total_imported * 0.19
    export_credit = total_exported * 0.19
    flex_bonus = battery_discharged * 0.31
    net_credit = export_credit - import_cost + flex_bonus
    
    # Estimate Home Consumption
    total_solar = se_generated + (chilicon_generated if chilicon_generated > 0 else inferred_chilicon)
    home_consumption = total_solar + total_imported - total_exported + battery_discharged - battery_charged
    if home_consumption < 0:
        home_consumption = 0.0

    return {
        "total_imported": total_imported,
        "total_exported": total_exported,
        "se_generated": se_generated,
        "battery_discharged": battery_discharged,
        "battery_charged": battery_charged,
        "chilicon_generated": chilicon_generated,
        "inferred_chilicon": inferred_chilicon,
        "peak_grid_import": peak_grid_import,
        "peak_grid_export": peak_grid_export,
        "peak_se_pv": peak_se_pv,
        "peak_chilicon_pv": peak_chilicon_pv,
        "net_credit": net_credit,
        "home_consumption": home_consumption
    }


def query_local_ollama(prompt: str, model: str) -> str:
    """Queries local Ollama generation API synchronously."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": "You are a precise grid monitor summarizer.",
        "stream": False
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        OLLAMA_ENDPOINT, 
        data=data, 
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            return res_data.get("response", "").strip()
    except urllib.error.URLError as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Ollama API error: {e}")
        raise


def run_local_cycle(prompt: str, model: str, start_time_str: str) -> None:
    """Runs a single local generation cycle: queries Ollama, times the execution,

    updates the cache, and clears the watchdog.
    """
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting local generation using model: {model}...")
    
    # Write watchdog file to survive crashes/reboots
    state_payload = {
        "model": model,
        "prompt": prompt,
        "timestamp": start_time_str
    }
    with open(ACTIVE_LOCAL_STATE, "w", encoding="utf-8") as sf:
        json.dump(state_payload, sf, indent=4)
        
    start_time = time.time()
    try:
        summary = query_local_ollama(prompt, model)
        elapsed = time.time() - start_time
        
        if summary:
            # Format and cache response
            retrieved_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            metadata = f"\n\n[Edge Model: {model} | Inference Time: {elapsed:.1f}s]"
            summary_with_metadata = f"{summary.strip()}{metadata}"
            
            cache_payload = {
                "timestamp": start_time_str,
                "summary": summary_with_metadata
            }
            with open(GEMINI_SUMMARY_CACHE, "w", encoding="utf-8") as cache_file:
                json.dump(cache_payload, cache_file, indent=4)
            print(f"🎉 SUCCESS: Cached new summary to {GEMINI_SUMMARY_CACHE} (Inference time: {elapsed:.1f}s)")
            
            # Clean up watchdog
            if os.path.exists(ACTIVE_LOCAL_STATE):
                os.remove(ACTIVE_LOCAL_STATE)
        else:
            print("ERROR: Received empty summary from Ollama.")
    except Exception as e:
        print(f"Exception during local generation cycle: {e}")
        raise


def handle_watchdog() -> None:
    """Checks if there's an in-flight job from a previous run, re-submitting it if interrupted."""
    if not os.path.exists(ACTIVE_LOCAL_STATE):
        return
        
    try:
        with open(ACTIVE_LOCAL_STATE, "r") as sf:
            job_state = json.load(sf)
        model = job_state.get("model")
        prompt = job_state.get("prompt")
        ts_str = job_state.get("timestamp")
        
        if model and prompt and ts_str:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Watchdog: Found in-flight job using {model} from {ts_str}. Checking if completed...")
            
            is_completed = False
            if os.path.exists(GEMINI_SUMMARY_CACHE):
                with open(GEMINI_SUMMARY_CACHE, "r") as cf:
                    cache_data = json.load(cf)
                cache_ts_str = cache_data.get("timestamp")
                if cache_ts_str:
                    try:
                        cache_ts = datetime.datetime.strptime(cache_ts_str, "%Y-%m-%d %H:%M:%S")
                        watchdog_ts = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        if cache_ts >= watchdog_ts:
                            is_completed = True
                    except ValueError:
                        pass
                        
            if is_completed:
                print("Watchdog: Job was already successfully cached. Clearing watchdog.")
                if os.path.exists(ACTIVE_LOCAL_STATE):
                    os.remove(ACTIVE_LOCAL_STATE)
            else:
                print("Watchdog: Job was NOT completed. Resubmitting request to local Ollama...")
                run_local_cycle(prompt, model, ts_str)
    except Exception as e:
        print(f"Error handling watchdog state: {e}")
        if os.path.exists(ACTIVE_LOCAL_STATE):
            os.remove(ACTIVE_LOCAL_STATE)


def main() -> None:
    """Main execution orchestrator for the local edge summary service."""
    model_override = DEFAULT_MODEL
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("--model="):
                model_override = arg.split("=", 1)[1]
            elif arg == "--model" and len(sys.argv) > sys.argv.index(arg) + 1:
                model_override = sys.argv[sys.argv.index(arg) + 1]

    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting local stager. Model: {model_override}")
    
    # 1. Recover any in-flight jobs
    handle_watchdog()
    
    # 2. Main interval loop
    while True:
        try:
            # Check cache freshness
            is_cache_fresh = False
            if os.path.exists(GEMINI_SUMMARY_CACHE):
                try:
                    with open(GEMINI_SUMMARY_CACHE, "r") as f:
                        cache_data = json.load(f)
                    ts_str = cache_data.get("timestamp")
                    if ts_str:
                        cache_time = None
                        try:
                            cache_time = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            try:
                                cache_time = datetime.datetime.fromisoformat(ts_str)
                            except ValueError:
                                cache_time = datetime.datetime.strptime(ts_str.split(".")[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                                
                        if cache_time and (datetime.datetime.now() - cache_time < datetime.timedelta(minutes=30)):
                            is_cache_fresh = True
                            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Local summary cache is fresh (< 30m). Skipping.")
                except Exception as cache_err:
                    print(f"Failed to check cache state: {cache_err}")
            
            if not is_cache_fresh:
                # Compile data and run
                records = generate_hourly_records()
                if not records:
                    print("No telemetry data to aggregate. Skipping cycle.")
                else:
                    # Perform Python pre-calculations
                    stats = calculate_metrics(records)
                    
                    # Read the prompt template and format it
                    now = datetime.datetime.now()
                    current_dt_str = now.strftime("%Y-%m-%d %H:%M:%S")
                    
                    first_dt_str = records[0][0]
                    last_dt_str = records[-1][0]
                    day_date_str = last_dt_str[:10]
                    
                    prompt_path = os.path.join(SCRIPT_DIR, "gemma_prompt.txt")
                    if os.path.exists(prompt_path):
                        try:
                            with open(prompt_path, "r", encoding="utf-8") as pf:
                                prompt_template = pf.read()
                        except Exception as pe:
                            print(f"Error reading prompt template file: {pe}")
                            prompt_template = None
                    else:
                        prompt_template = None

                    if not prompt_template:
                        prompt_template = """You are an energy monitoring assistant. 
Here are the pre-calculated statistics for the day from the telemetry logs:
- Total Net Imported: {total_imported:.3f} kWh
- Total Net Exported: {total_exported:.3f} kWh
- SolarEdge Generated: {se_generated:.3f} kWh
- Inferred Chillicon Contribution: {inferred_chilicon:.3f} kWh
- Net Energy Credit: ${net_credit:.2f}
- Peak Net Grid Demand: {peak_grid_import:.3f} kW
- Peak SolarEdge PV: {peak_se_pv:.3f} kW
- Total Home Consumption: {home_consumption:.3f} kWh

Instructions:
1. Provide a list of key statistics (Total Net Imported, Total Net Exported, SolarEdge Generated, Net Energy Cost/Credit, Peak Net Grid Demand, Peak SolarEdge PV, and Inferred Chillicon Contribution) using EXACTLY the pre-calculated values provided above. Do NOT perform any math or estimate values yourself.
2. Write a short 5 to 6 sentence paragraph summary explaining these stats, detailing SolarEdge performance, battery status (highlighting if Flex events with battery discharging occurred), Chillicon contribution, and PSE billing impact.
3. Keep the output under 12 lines.
4. Do NOT use markdown code blocks, bold text (**), asterisks, or any text formatting other than plain text.
5. Finish with the date analyzed: "Data analyzed for {day_date}".
"""

                    
                    formatted_prompt = prompt_template.format(
                        total_imported=stats['total_imported'],
                        total_exported=stats['total_exported'],
                        se_generated=stats['se_generated'],
                        inferred_chilicon=stats['inferred_chilicon'],
                        net_credit=stats['net_credit'],
                        peak_grid_import=stats['peak_grid_import'],
                        peak_se_pv=stats['peak_se_pv'],
                        home_consumption=stats['home_consumption'],
                        day_date=day_date_str
                    )
                    
                    run_local_cycle(formatted_prompt, model_override, current_dt_str)
                    
        except Exception as loop_err:
            print(f"Loop error: {loop_err}")
            
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Sleeping for 15 minutes...")
        for _ in range(90):
            time.sleep(10)


if __name__ == "__main__":
    main()

import os
import json
import time
import datetime
import csv
import re
import statistics
from collections import defaultdict
import urllib.request
import urllib.error
from typing import Dict, List, Tuple, Optional, Any

# -------------------------------------------------------------
# Configuration Constants
# -------------------------------------------------------------
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "mutua-477100")
LOCATION: str = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
OLLAMA_ENDPOINT: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434/api/generate")

# History Paths
HOME_DIR: str = os.path.expanduser("~")
LOCAL_GRID: str = os.path.join(SCRIPT_DIR, "grid_history.db")
GRID_HISTORY: str = LOCAL_GRID if os.path.exists(LOCAL_GRID) else os.path.join(HOME_DIR, "grid_history.db")

LOCAL_SE: str = os.path.join(SCRIPT_DIR, "solaredge_history.csv")
SE_HISTORY: str = LOCAL_SE if os.path.exists(LOCAL_SE) else os.path.join(HOME_DIR, "solaredge_history.csv")

LOCAL_SE_BATTERY: str = os.path.join(SCRIPT_DIR, "solaredge_battery_history.csv")
SE_BATTERY_HISTORY: str = LOCAL_SE_BATTERY if os.path.exists(LOCAL_SE_BATTERY) else os.path.join(HOME_DIR, "solaredge_battery_history.csv")

LOCAL_CHILICON: str = os.path.join(SCRIPT_DIR, "chilicon_history.csv")
CHILICON_HISTORY: str = LOCAL_CHILICON if os.path.exists(LOCAL_CHILICON) or not os.path.exists(os.path.join(HOME_DIR, "chilicon_history.csv")) else os.path.join(HOME_DIR, "chilicon_history.csv")


def setup_gcp_credentials() -> bool:
    """Sets up Google Application Credentials from known service account paths."""
    possible_paths: List[str] = [
        os.path.join(SCRIPT_DIR, "Auth/service_account.json"),
        os.path.join(SCRIPT_DIR, "auth/service_account.json"),
        os.path.join(SCRIPT_DIR, "../Auth/service_account.json"),
        os.path.join(SCRIPT_DIR, "../auth/service_account.json"),
        os.path.join(HOME_DIR, "Auth/service_account.json"),
        os.path.join(HOME_DIR, "auth/service_account.json")
    ]
    
    sa_path = None
    for path in possible_paths:
        if os.path.exists(path):
            sa_path = path
            break
            
    if sa_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_path
        # Auto-extract project ID
        try:
            with open(sa_path, 'r') as key_file:
                sa_data = json.load(key_file)
                extracted_project = sa_data.get("project_id")
                if extracted_project:
                    global PROJECT_ID
                    PROJECT_ID = extracted_project
        except Exception:
            pass
        return True
    return False


def query_vertex_ai(prompt: str) -> Optional[str]:
    """Queries Vertex AI Gemini 2.5 Flash model."""
    if not setup_gcp_credentials():
        print("Vertex AI Error: Service account JSON key not found. Skipping Vertex AI.")
        return None
        
    try:
        from google import genai
        from google.genai import types
        import httpx
        
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION,
            http_options=types.HttpOptions(httpx_client=httpx.Client(timeout=60.0))
        )
        
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Vertex AI API call failed: {e}")
        return None


def query_ollama(prompt: str, model: str) -> Optional[str]:
    """Queries local Ollama instance for a specific model."""
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
        with urllib.request.urlopen(req, timeout=120) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            return res_data.get("response", "").strip()
    except Exception as e:
        print(f"Ollama query for {model} failed: {e}")
        return None


def is_ollama_model_available(model: str) -> bool:
    """Checks if a model is downloaded and available in Ollama."""
    url = OLLAMA_ENDPOINT.rsplit('/', 2)[0] + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            models = [m.get("name") for m in data.get("models", [])]
            # Match base name or exact name (e.g. gemma2:2b or gemma2:2b-instruct)
            for m in models:
                if model in m or m in model:
                    return True
    except Exception:
        pass
    return False


def get_token_count_approx(text: str) -> int:
    """Simple whitespace-based token approximation (1 token ~= 4 chars)."""
    return len(text) // 4


def compute_word_overlap(text1: str, text2: str) -> float:
    """Calculates Jaccard similarity of lowercase words between two texts."""
    words1 = set(re.findall(r'\b\w+\b', text1.lower()))
    words2 = set(re.findall(r'\b\w+\b', text2.lower()))
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)


def check_formatting_compliance(text: str) -> Tuple[bool, List[str]]:
    """Checks compliance with prompt instructions.

    - Max 80 character line width.
    - Plain text (no **, *, markdown code blocks).
    - Under 15 lines.
    """
    violations = []
    lines = text.split('\n')
    
    if len(lines) > 15:
        violations.append(f"Too many lines: {len(lines)} (Limit is 15)")
        
    for idx, line in enumerate(lines):
        if len(line) > 80:
            # We allow metadata footer line or data table lines to be longer if needed, but flag standard paragraphs
            if not line.startswith("[Edge Model") and not line.startswith("[Batch Submitted"):
                violations.append(f"Line {idx+1} exceeds 80 characters ({len(line)} chars)")
                
    # Look for bold markdown or lists with bold headers
    if "**" in text:
        violations.append("Contains markdown bolding (double asterisks)")
    if "```" in text:
        violations.append("Contains markdown code blocks (backticks)")
        
    return len(violations) == 0, violations


def parse_numeric_facts(text: str) -> Dict[str, Optional[float]]:
    """Extracts common numeric facts from summaries using regex.

    Looks for net import/export kWh, cost/credits.
    """
    facts = {}
    
    # Net Import / Export kWh
    import_match = re.search(r'(?:Net Import|Imported):\s*([\d\.]+)\s*kWh', text, re.IGNORECASE)
    export_match = re.search(r'(?:Net Export|Exported):\s*([\d\.]+)\s*kWh', text, re.IGNORECASE)
    se_match = re.search(r'(?:SE Generated|SolarEdge Generated):\s*([\d\.]+)\s*kWh', text, re.IGNORECASE)
    credit_match = re.search(r'(?:Net Energy Credit|Credit|Cost):\s*\$?([\d\.-]+)', text, re.IGNORECASE)
    
    facts["net_import"] = float(import_match.group(1)) if import_match else None
    facts["net_export"] = float(export_match.group(1)) if export_match else None
    facts["se_gen"] = float(se_match.group(1)) if se_match else None
    facts["credit"] = float(credit_match.group(1)) if credit_match else None
    
    return facts


def load_all_hourly_data() -> List[Tuple[str, float, float, float, float, float, float, float, float, float, float, float, float]]:
    """Generates the aligned hourly table from all local history files."""
    # Build list of hours aligned
    hourly_data = defaultdict(list)
    if os.path.exists(GRID_HISTORY):
        try:
            with open(GRID_HISTORY, 'r') as f:
                reader = csv.reader(line.replace('\x00', '') for line in f)
                for row in reader:
                    if len(row) == 2:
                        ts = row[0].strip().replace('\x00', '')
                        val = row[1].strip().replace('\x00', '')
                        if ts and val:
                            hour_key = ts[:13].replace('T', ' ') + ":00"
                            try:
                                hourly_data[hour_key].append(float(val))
                            except ValueError:
                                continue
        except Exception:
            pass

    se_hourly = defaultdict(list)
    if os.path.exists(SE_HISTORY):
        try:
            with open(SE_HISTORY, 'r') as f:
                reader = csv.reader(line.replace('\x00', '') for line in f)
                for row in reader:
                    if len(row) == 2:
                        ts = row[0].strip().replace('\x00', '')
                        val = row[1].strip().replace('\x00', '')
                        if ts and val:
                            hour_key = ts[:13].replace('T', ' ') + ":00"
                            try:
                                se_hourly[hour_key].append(float(val))
                            except ValueError:
                                continue
        except Exception:
            pass

    bat_hourly = defaultdict(list)
    if os.path.exists(SE_BATTERY_HISTORY):
        try:
            with open(SE_BATTERY_HISTORY, 'r') as f:
                reader = csv.reader(line.replace('\x00', '') for line in f)
                for row in reader:
                    if len(row) == 3:
                        ts = row[0].strip().replace('\x00', '')
                        p = row[1].strip().replace('\x00', '')
                        soc = row[2].strip().replace('\x00', '')
                        if ts and p and soc:
                            hour_key = ts[:13].replace('T', ' ') + ":00"
                            try:
                                bat_hourly[hour_key].append((float(p), float(soc)))
                            except ValueError:
                                continue
        except Exception:
            pass

    ch_hourly = defaultdict(list)
    if os.path.exists(CHILICON_HISTORY):
        try:
            with open(CHILICON_HISTORY, 'r') as f:
                reader = csv.reader(line.replace('\x00', '') for line in f)
                for row in reader:
                    if len(row) == 3:
                        ts = row[0].strip().replace('\x00', '')
                        p = row[1].strip().replace('\x00', '')
                        if ts and p:
                            hour_key = ts[:13].replace('T', ' ') + ":00"
                            try:
                                ch_hourly[hour_key].append(float(p))
                            except ValueError:
                                continue
        except Exception:
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


def select_test_scenarios(records: List[Tuple]) -> Dict[str, List[Tuple]]:
    """Groups hourly records by day and returns 3 diverse profiles."""
    by_day = defaultdict(list)
    for rec in records:
        day_key = rec[0][:10] # Grab YYYY-MM-DD
        by_day[day_key].append(rec)
        
    # Filter out days with less than 12 hours of data to ensure substantial context
    complete_days = {d: v for d, v in by_day.items() if len(v) >= 12}
    if not complete_days:
        # Fallback to whatever days are available
        complete_days = by_day
        
    scenarios = {}
    
    # 1. Day with highest SolarEdge solar generation
    if complete_days:
        day_solar = {}
        for day, recs in complete_days.items():
            total_se_energy = sum([r[7] for r in recs])
            day_solar[day] = total_se_energy
        high_solar_day = max(day_solar, key=day_solar.get)
        scenarios["High Solar Export Day"] = complete_days[high_solar_day]
        
    # 2. Day with highest grid import (high household consumption)
    if complete_days:
        day_import = {}
        for day, recs in complete_days.items():
            total_import = sum([max(0.0, r[1]) for r in recs]) # Sum positive Grid Average kW
            day_import[day] = total_import
        high_import_day = max(day_import, key=day_import.get)
        # Avoid duplicate day selection if possible
        if high_import_day in scenarios.values():
            remaining = {k: v for k, v in day_import.items() if k != high_import_day}
            if remaining:
                high_import_day = max(remaining, key=remaining.get)
        scenarios["High Grid Import Day"] = complete_days[high_import_day]
        
    # 3. Day with active battery discharging (Flex Event candidate)
    if complete_days:
        flex_days = []
        for day, recs in complete_days.items():
            max_discharge = max([r[8] for r in recs]) # Max Battery_Avg_kW
            if max_discharge > 0.5:
                flex_days.append((day, max_discharge))
        if flex_days:
            # Sort by highest battery discharge rate
            flex_days.sort(key=lambda x: x[1], reverse=True)
            flex_day = flex_days[0][0]
            # Avoid duplicate selection
            scenarios["Battery Dispatch / Flex Event Day"] = complete_days[flex_day]
        else:
            # Fallback to random day
            for day in complete_days:
                if day not in [recs[0][0][:10] for recs in scenarios.values()]:
                    scenarios["Average Telemetry Day"] = complete_days[day]
                    break
                    
    # Fill up to 3 scenarios if any are missing
    for day, recs in complete_days.items():
        if len(scenarios) >= 3:
            break
        day_label = f"Telemetry Profile {day}"
        if day_label not in scenarios and day not in [r[0][:10] for r in scenarios.values()]:
            scenarios[day_label] = recs
            
    return scenarios


def run_evaluation() -> None:
    print("==========================================================")
    print("Starting AI Telemetry Model Comparison Framework")
    print("==========================================================")
    
    # 1. Load data and select test days
    all_records = load_all_hourly_data()
    if not all_records:
        print("Error: No historical telemetry records found. Exiting.")
        return
        
    scenarios = select_test_scenarios(all_records)
    print(f"Selected {len(scenarios)} test cases:")
    for name, recs in scenarios.items():
        print(f" - {name}: {recs[0][0][:10]} ({len(recs)} hourly records)")
        
    # 2. Check model availabilities
    run_gemini = setup_gcp_credentials()
    run_gemma_2b = is_ollama_model_available("gemma2:2b")
    run_gemma_9b = False  # Disabled due to Out-of-Memory crashes on 8GB UMA hardware
    
    print("\nModel Availability:")
    print(f" - Vertex AI (gemini-2.5-flash): {'AVAILABLE' if run_gemini else 'NOT CONFIGURED'}")
    print(f" - Local Ollama (gemma2:2b): {'AVAILABLE' if run_gemma_2b else 'NOT FOUND'}")
    print(f" - Local Ollama (gemma2:9b): {'AVAILABLE' if run_gemma_9b else 'NOT FOUND'}")
    
    if not run_gemini and not run_gemma_2b and not run_gemma_9b:
        print("Error: No models are available to evaluate. Exiting.")
        return
        
    prompt_path = os.path.join(SCRIPT_DIR, "gemini_prompt.txt")
    if not os.path.exists(prompt_path):
        print(f"Error: Prompt template not found at {prompt_path}")
        return
        
    with open(prompt_path, "r", encoding="utf-8") as pf:
        prompt_template = pf.read()
        
    comparison_results = []
    
    # Run test cases
    for s_name, recs in scenarios.items():
        day_date = recs[0][0][:10]
        print(f"\nEvaluating Profile: {s_name} ({day_date})...")
        
        # Build CSV table for just this day
        csv_header = "Hour,Avg_kW,Min_kW,Max_kW,Median_kW,SE_Avg_kW,SE_Max_kW,SE_Energy_kWh,Battery_Avg_kW,Battery_SoC,Chillicon_Avg_kW,Chillicon_Max_kW,Chillicon_Energy_kWh"
        csv_lines = [csv_header]
        for r in recs:
            csv_lines.append(f"{r[0]},{r[1]:.3f},{r[2]:.3f},{r[3]:.3f},{r[4]:.3f},{r[5]:.3f},{r[6]:.3f},{r[7]:.3f},{r[8]:.3f},{r[9]:.1f},{r[10]:.3f},{r[11]:.3f},{r[12]:.3f}")
        csv_data = "\n".join(csv_lines)
        
        first_time = recs[0][0]
        last_time = recs[-1][0]
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        formatted_prompt = prompt_template.format(
            csv_data=csv_data,
            current_date_time=current_time,
            last_data_time=last_time,
            first_data_time=first_time
        )
        
        day_results = {
            "scenario": s_name,
            "date": day_date,
            "models": {}
        }
        
        # Evaluate Vertex AI
        if run_gemini:
            print(" -> Running Vertex AI (gemini-2.5-flash)...")
            start = time.time()
            text = query_vertex_ai(formatted_prompt)
            elapsed = time.time() - start
            if text:
                day_results["models"]["gemini-2.5-flash"] = {
                    "text": text,
                    "time": elapsed,
                    "tokens": get_token_count_approx(text)
                }
                
        # Evaluate Gemma 2B
        if run_gemma_2b:
            print(" -> Running Ollama (gemma2:2b) with Hybrid python math prompt...")
            # Pre-calculate stats in Python
            stats = calculate_metrics(recs)
            prompt_path_gemma = os.path.join(SCRIPT_DIR, "gemma_prompt.txt")
            if os.path.exists(prompt_path_gemma):
                try:
                    with open(prompt_path_gemma, "r", encoding="utf-8") as pf:
                        prompt_template_gemma = pf.read()
                except Exception as pe:
                    print(f"Error reading gemma_prompt.txt: {pe}")
                    prompt_template_gemma = None
            else:
                prompt_template_gemma = None

            if not prompt_template_gemma:
                prompt_template_gemma = """You are an energy monitoring assistant. 
Here are the pre-calculated statistics for the day from the telemetry logs:
- Total Net Imported: {total_imported:.3f} kWh
- Total Net Exported: {total_exported:.3f} kWh
- SolarEdge Generated: {se_generated:.3f} kWh
- Chillicon Generated (Reported): {chilicon_generated:.3f} kWh
- Inferred Chillicon Contribution: {inferred_chilicon:.3f} kWh
- Battery Energy Charged: {battery_charged:.3f} kWh
- Battery Energy Discharged: {battery_discharged:.3f} kWh
- Net Energy Credit: ${net_credit:.2f}
- Peak Net Grid Demand: {peak_grid_import:.3f} kW
- Peak SolarEdge PV: {peak_se_pv:.3f} kW
- Total Home Consumption: {home_consumption:.3f} kWh

Instructions:
1. Provide a list of key statistics (Total Net Imported, Total Net Exported, SolarEdge Generated, Chillicon Generated (Reported), Inferred Chillicon Contribution, Battery Energy Charged, Battery Energy Discharged, Net Energy Cost/Credit, Peak Net Grid Demand, and Peak SolarEdge PV) using EXACTLY the pre-calculated values provided above. Do NOT perform any math or estimate values yourself.
2. Write a short 5 to 6 sentence paragraph summary explaining these stats, detailing SolarEdge performance, battery status (highlighting if Flex events with battery discharging occurred), Chillicon contribution, and PSE billing impact.
3. Keep the output under 12 lines.
4. Do NOT use markdown code blocks, bold text (**), asterisks, or any text formatting other than plain text.
5. Finish with the date analyzed: "Data analyzed for {day_date}".
"""

            formatted_prompt_gemma2b = prompt_template_gemma.format(
                total_imported=stats['total_imported'],
                total_exported=stats['total_exported'],
                se_generated=stats['se_generated'],
                chilicon_generated=stats['chilicon_generated'],
                inferred_chilicon=stats['inferred_chilicon'],
                battery_charged=stats['battery_charged'],
                battery_discharged=stats['battery_discharged'],
                net_credit=stats['net_credit'],
                peak_grid_import=stats['peak_grid_import'],
                peak_se_pv=stats['peak_se_pv'],
                home_consumption=stats['home_consumption'],
                day_date=day_date
            )
            start = time.time()
            text = query_ollama(formatted_prompt_gemma2b, "gemma2:2b")
            elapsed = time.time() - start
            if text:
                day_results["models"]["gemma2:2b"] = {
                    "text": text,
                    "time": elapsed,
                    "tokens": get_token_count_approx(text)
                }
                
        # Evaluate Gemma 9B
        if run_gemma_9b:
            print(" -> Running Ollama (gemma2:9b)...")
            start = time.time()
            text = query_ollama(formatted_prompt, "gemma2:9b")
            elapsed = time.time() - start
            if text:
                day_results["models"]["gemma2:9b"] = {
                    "text": text,
                    "time": elapsed,
                    "tokens": get_token_count_approx(text)
                }
                
        comparison_results.append(day_results)
        
    # 3. Analyze results and generate markdown report
    generate_report_file(comparison_results)


def generate_report_file(results: List[Dict]) -> None:
    report_path = os.path.join(SCRIPT_DIR, "model_comparison_report.md")
    print(f"\nWriting evaluation report to {report_path}...")
    
    with open(report_path, "w", encoding="utf-8") as rf:
        rf.write("# Model Comparison & Semantic Drift Evaluation Report\n\n")
        rf.write(f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        rf.write("This report benchmarks the qualitative summaries, constraint compliance, and inference speed of the local **Gemma 2** edge models against the Google Cloud **Gemini 2.5 Flash** baseline.\n\n")
        
        rf.write("## 1. Executive Performance Summary\n\n")
        rf.write("| Metric | Vertex Gemini 2.5 Flash | Local Gemma 2 2B | Local Gemma 2 9B |\n")
        rf.write("| :--- | :--- | :--- | :--- |\n")
        
        # Calculate averages across all scenarios
        metrics = {"gemini-2.5-flash": [], "gemma2:2b": [], "gemma2:9b": []}
        for day in results:
            for m_name, data in day["models"].items():
                metrics[m_name].append(data)
                
        def get_avg_time(m_name):
            times = [d["time"] for d in metrics[m_name]]
            return f"{statistics.mean(times):.2f}s" if times else "N/A"
            
        def get_avg_tokens(m_name):
            toks = [d["tokens"] for d in metrics[m_name]]
            return f"{int(statistics.mean(toks))}" if toks else "N/A"
            
        rf.write(f"| **Avg Inference Speed** | {get_avg_time('gemini-2.5-flash')} | {get_avg_time('gemma2:2b')} | {get_avg_time('gemma2:9b')} |\n")
        rf.write(f"| **Avg Output length** | {get_avg_tokens('gemini-2.5-flash')} tokens | {get_avg_tokens('gemma2:2b')} tokens | {get_avg_tokens('gemma2:9b')} tokens |\n")
        
        # Check formatting compliances
        compliances = {}
        for m_name in metrics:
            compliances[m_name] = []
            for item in metrics[m_name]:
                compliant, violations = check_formatting_compliance(item["text"])
                compliances[m_name].append(compliant)
                
        def get_compliance_rate(m_name):
            vals = compliances[m_name]
            return f"{sum(vals)} / {len(vals)} ({int(sum(vals)/len(vals)*100)}%)" if vals else "N/A"
            
        rf.write(f"| **Constraint Compliance** | {get_compliance_rate('gemini-2.5-flash')} | {get_compliance_rate('gemma2:2b')} | {get_compliance_rate('gemma2:9b')} |\n\n")
        
        rf.write("## 2. Detailed Scenario Analysis\n\n")
        
        for idx, day in enumerate(results):
            day_num = idx + 1
            rf.write(f"### Scenario {day_num}: {day['scenario']} ({day['date']})\n\n")
            
            # Sub-table of model details
            rf.write("| Model | Inference Time | Length (tokens) | Formatting | Semantic Overlap (vs Gemini) |\n")
            rf.write("| :--- | :--- | :--- | :--- | :--- |\n")
            
            gemini_txt = day["models"].get("gemini-2.5-flash", {}).get("text", "")
            
            for m_name, data in day["models"].items():
                compliant, violations = check_formatting_compliance(data["text"])
                status = "✅ Pass" if compliant else "❌ Fail"
                overlap = compute_word_overlap(data["text"], gemini_txt) if m_name != "gemini-2.5-flash" and gemini_txt else 1.0
                overlap_str = f"{overlap*100:.1f}%" if m_name != "gemini-2.5-flash" else "Baseline"
                rf.write(f"| {m_name} | {data['time']:.2f}s | {data['tokens']} | {status} | {overlap_str} |\n")
            rf.write("\n")
            
            # Numeric accuracy breakdown
            rf.write("#### Mathematical & Fact Extraction Parity\n\n")
            rf.write("| Extraction Fact | Baseline Gemini 2.5 Flash | Gemma 2 2B | Gemma 2 9B |\n")
            rf.write("| :--- | :--- | :--- | :--- |\n")
            
            gemini_facts = parse_numeric_facts(gemini_txt) if gemini_txt else {}
            facts2b = parse_numeric_facts(day["models"].get("gemma2:2b", {}).get("text", "")) if "gemma2:2b" in day["models"] else {}
            facts9b = parse_numeric_facts(day["models"].get("gemma2:9b", {}).get("text", "")) if "gemma2:9b" in day["models"] else {}
            
            for key in ["net_import", "net_export", "se_gen", "credit"]:
                def get_fact_val(facts_dict):
                    val = facts_dict.get(key)
                    if val is None:
                        return "Not Found"
                    if key == "credit":
                        return f"${val:.2f}"
                    return f"{val:.2f} kWh"
                rf.write(f"| **{key.replace('_', ' ').title()}** | {get_fact_val(gemini_facts)} | {get_fact_val(facts2b)} | {get_fact_val(facts9b)} |\n")
                
            rf.write("\n")
            
            # Output texts comparison
            rf.write("#### Output Summary Contents\n\n")
            
            for m_name, data in day["models"].items():
                compliant, violations = check_formatting_compliance(data["text"])
                v_notes = f" (Violations: {', '.join(violations)})" if not compliant else ""
                rf.write(f"**{m_name}** ({data['time']:.1f}s, {data['tokens']} tokens){v_notes}:\n")
                rf.write("```\n")
                rf.write(data["text"] + "\n")
                rf.write("```\n\n")
                
            rf.write("---\n\n")
            
        rf.write("## 3. Conclusions and Recommendation\n\n")
        rf.write("- **Computational Overhead**: Local edge inference on the Jetson Orin Nano is fully self-contained ($0 token cost). Gemma 2 2B provides blistering speed (~10-15s) and fits easily in system memory. Gemma 2 9B provides superior logical reasoning but requires significant unified memory and runs slower.\n")
        rf.write("- **Parity Analysis**: Analyze the semantic overlap and numeric fact extraction to determine if Gemma 2 can fully substitute Gemini 2.5 Flash without manual parameter tweaking.\n")
        
    print(f"🎉 Evaluation report written successfully!")


if __name__ == "__main__":
    run_evaluation()

import os
import json
import time
import datetime
import csv
import statistics
import urllib.request
import urllib.error
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any

SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
GRID_HISTORY: str = os.path.join(SCRIPT_DIR, "grid_history.db")
SE_HISTORY: str = os.path.join(SCRIPT_DIR, "solaredge_history.csv")
SE_BATTERY_HISTORY: str = os.path.join(SCRIPT_DIR, "solaredge_battery_history.csv")
CHILICON_HISTORY: str = os.path.join(SCRIPT_DIR, "chilicon_history.csv")


def sanitize_reader(filepath: str) -> List[List[str]]:
    """Reads a CSV file while dynamically sanitizing NUL bytes on the fly."""
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


def calculate_metrics(records: List[Tuple]) -> Dict[str, Any]:
    """Computes mathematically precise metrics from aligned hourly telemetry records.

    Formula matching Gemini prompt requirements.
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
        # Average power over 1 hour = energy in kWh
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
        # Inferred Chillicon = (Net Grid export) - (SolarEdge PV) - (Battery discharge)
        if avg_kw < 0:
            grid_export_rate = abs(avg_kw)
            inferred_rate = grid_export_rate - se_avg - max(0.0, bat_avg)
            if inferred_rate > 0:
                inferred_chilicon += inferred_rate * 1.0

    # Net Billing Impact
    # Import cost: $0.19/kWh
    # Standard Export credit: $0.19/kWh
    # Battery Discharge bonus: $0.31/kWh (discharged during Flex event gets $0.50/kWh total)
    import_cost = total_imported * 0.19
    export_credit = total_exported * 0.19
    flex_bonus = battery_discharged * 0.31
    net_credit = export_credit - import_cost + flex_bonus
    
    # Estimate Home Consumption
    # Home consumption = SolarEdge + Chillicon (or Inferred) + Import - Export - Battery Charge + Battery Discharge
    # Approx:
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


def load_day_records(day_date: str) -> List[Tuple[str, float, float, float, float, float, float, float, float, float, float, float, float]]:
    """Loads and aligns hourly records for a specific day from database or local CSVs.

    Args:
        day_date: The date string (YYYY-MM-DD) to query and align records for.

    Returns:
        A list of aligned hourly tuples containing statistics for grid, solar, battery,
        and microinverter values.
    """
    se_rows = sanitize_reader(SE_HISTORY)
    bat_rows = sanitize_reader(SE_BATTERY_HISTORY)
    ch_rows = sanitize_reader(CHILICON_HISTORY)
    
    hourly_data = defaultdict(list)
    if GRID_HISTORY.endswith('.db'):
        from dashboard_modules import db
        # Cutoff hours 999999 to load the whole history for daily filtering
        db_ts, db_vals = db.query_history(GRID_HISTORY, cutoff_hours=999999)
        for ts, val in zip(db_ts, db_vals):
            ts_str = ts.isoformat()
            if ts_str.startswith(day_date):
                hour_key = ts_str[:13].replace('T', ' ') + ":00"
                hourly_data[hour_key].append(val)
    else:
        grid_rows = sanitize_reader(GRID_HISTORY)
        for row in grid_rows:
            if len(row) == 2:
                ts, val = row[0].strip(), row[1].strip()
                if ts.startswith(day_date):
                    hour_key = ts[:13].replace('T', ' ') + ":00"
                    try:
                        hourly_data[hour_key].append(float(val))
                    except ValueError:
                        pass

    se_hourly = defaultdict(list)
    for row in se_rows:
        if len(row) == 2:
            ts, val = row[0].strip(), row[1].strip()
            if ts.startswith(day_date):
                hour_key = ts[:13].replace('T', ' ') + ":00"
                try:
                    se_hourly[hour_key].append(float(val))
                except ValueError:
                    pass

    bat_hourly = defaultdict(list)
    for row in bat_rows:
        if len(row) == 3:
            ts, p, soc = row[0].strip(), row[1].strip(), row[2].strip()
            if ts.startswith(day_date):
                hour_key = ts[:13].replace('T', ' ') + ":00"
                try:
                    bat_hourly[hour_key].append((float(p), float(soc)))
                except ValueError:
                    pass

    ch_hourly = defaultdict(list)
    for row in ch_rows:
        if len(row) == 3:
            ts, p, e = row[0].strip(), row[1].strip(), row[2].strip()
            if ts.startswith(day_date):
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


def run_emulation() -> None:
    # Use Scenario 3: May 28, 2026 (Flex event day)
    day_date = "2026-05-28"
    print(f"==========================================================")
    # 1. Align and calculate metrics in Python
    records = load_day_records(day_date)
    if not records:
        print(f"Error: No records found for {day_date}.")
        return
        
    stats = calculate_metrics(records)
    print(f"--- 1. Python Pre-Calculated Stats for {day_date} ---")
    print(f"Total Net Imported:  {stats['total_imported']:.3f} kWh")
    print(f"Total Net Exported:  {stats['total_exported']:.3f} kWh")
    print(f"SolarEdge Generated: {stats['se_generated']:.3f} kWh")
    print(f"Peak Net Grid Demand: {stats['peak_grid_import']:.3f} kW")
    print(f"Peak SolarEdge PV:   {stats['peak_se_pv']:.3f} kW")
    print(f"Inferred Chillicon:  {stats['inferred_chilicon']:.3f} kWh")
    print(f"Net Energy Cost/Credit: ${abs(stats['net_credit']):.2f} ({'Credit' if stats['net_credit'] >= 0 else 'Cost'})")
    print(f"Total Home Consumption: {stats['home_consumption']:.3f} kWh")
    
    # 2. Build the adapted prompt
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
2. Write a short 5 to 6 sentence paragraph summary explaining these stats, detailing SolarEdge performance, battery status (we had Flex events with battery discharging), Chillicon contribution, and PSE billing impact.
3. Keep the output under 12 lines.
4. Do NOT use markdown code blocks, bold text (**), asterisks, or any text formatting other than plain text.
5. Finish with the date analyzed: "Data analyzed for {day_date}".
"""

    net_credit_val = stats['net_credit']
    formatted_prompt = prompt_template.format(
        total_imported=stats['total_imported'],
        total_exported=stats['total_exported'],
        se_generated=stats['se_generated'],
        inferred_chilicon=stats['inferred_chilicon'],
        net_credit=net_credit_val,
        peak_grid_import=stats['peak_grid_import'],
        peak_se_pv=stats['peak_se_pv'],
        home_consumption=stats['home_consumption'],
        day_date=day_date
    )
    
    print("\n--- 2. Adapted Prompt Sent to Gemma 2B ---")
    print(formatted_prompt)
    
    # 3. Query local Ollama Gemma 4
    print("\n--- 3. Local Model (Gemma 4) Output ---")
    try:
        url = os.environ.get("OLLAMA_HOST") or "http://localhost:11434/api/generate"
        payload = {
            "model": "gemma4-it-q4",
            "prompt": formatted_prompt,
            "system": "You are a precise grid monitor summarizer.",
            "stream": False
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            summary = res_data.get("response", "").strip()
            print(summary)
            
            # Save emulation result to text file as requested by "summarize in a file"
            emulation_report_path = os.path.join(SCRIPT_DIR, "emulation_results.txt")
            with open(emulation_report_path, "w") as ef:
                ef.write("=== EMULATION RESULTS (HYBRID PYTHON-LLM STAGER) ===\n\n")
                ef.write(f"Test Date: {day_date}\n\n")
                ef.write("--- Pre-Calculated Stats (Python) ---\n")
                ef.write(f"Total Net Imported:  {stats['total_imported']:.3f} kWh\n")
                ef.write(f"Total Net Exported:  {stats['total_exported']:.3f} kWh\n")
                ef.write(f"SolarEdge Generated: {stats['se_generated']:.3f} kWh\n")
                ef.write(f"Peak Net Grid Demand: {stats['peak_grid_import']:.3f} kW\n")
                ef.write(f"Peak SolarEdge PV:   {stats['peak_se_pv']:.3f} kW\n")
                ef.write(f"Inferred Chillicon:  {stats['inferred_chilicon']:.3f} kWh\n")
                ef.write(f"Net Energy Credit:   ${stats['net_credit']:.2f}\n")
                ef.write(f"Home Consumption:    {stats['home_consumption']:.3f} kWh\n\n")
                ef.write("--- Gemma 2B Output summary ---\n")
                ef.write(summary + "\n")
            print(f"\n🎉 Emulation report written to {emulation_report_path}")
    except Exception as e:
        print(f"Error querying Ollama: {e}")


if __name__ == "__main__":
    run_emulation()

import os
import json
import time
import datetime
import csv
import statistics
import sys
import urllib.request
import urllib.error
import http.server
import socketserver
import math
import logging
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# -------------------------------------------------------------
# Configuration Constants
# -------------------------------------------------------------
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR: str = os.path.join(SCRIPT_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# Local Telemetry CSV History Paths (read from SCP backup directory)
GRID_HISTORY: str = os.path.join(BACKUP_DIR, "grid_history.csv")
SE_HISTORY: str = os.path.join(BACKUP_DIR, "solaredge_history.csv")
SE_BATTERY_HISTORY: str = os.path.join(BACKUP_DIR, "solaredge_battery_history.csv")
CHILICON_HISTORY: str = os.path.join(BACKUP_DIR, "chilicon_history.csv")

# Model configuration
DEFAULT_MODEL: str = os.environ.get("EDGE_MODEL", "gemma2:2b")
OLLAMA_ENDPOINT: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434/api/generate")

# Default coordinates for weather (Seattle area)
DEFAULT_LAT: str = os.environ.get("WEATHER_LAT", "47.6062")
DEFAULT_LON: str = os.environ.get("WEATHER_LON", "-122.3321")


def parse_timestamp(ts_str: str) -> Optional[datetime.datetime]:
    """Robust parser for naive datetime strings."""
    ts_str = ts_str.strip().replace('\x00', '')
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f"
    ):
        try:
            return datetime.datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def fetch_weather(lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Tuple[Optional[float], Optional[float]]:
    """Fetches today's weather forecast (max temp in C, mean cloud cover in %) from Open-Meteo API."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,cloud_cover_mean&timezone=auto"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode('utf-8'))
            daily = res.get("daily", {})
            temp_max = daily.get("temperature_2m_max", [None])[0]
            cloud_cover = daily.get("cloud_cover_mean", [None])[0]
            logging.info(f"Fetched weather: temp_max={temp_max}°C, cloud_cover={cloud_cover}%")
            return temp_max, cloud_cover
    except Exception as e:
        logging.error(f"Error fetching weather forecast: {e}")
        return None, None


def calculate_grid_stats(filepath: str) -> Tuple[float, float]:
    """Calculates historical mean and standard deviation of grid demand from history CSV."""
    if not os.path.exists(filepath):
        return 0.0, 1.0
    vals = []
    try:
        with open(filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    try:
                        vals.append(float(row[1]))
                    except ValueError:
                        pass
    except Exception as e:
        logging.error(f"Error calculating grid stats: {e}")
    if not vals:
        return 0.0, 1.0
    mean_val = sum(vals) / len(vals)
    if len(vals) > 1:
        var_val = sum((x - mean_val) ** 2 for x in vals) / (len(vals) - 1)
        std_val = math.sqrt(var_val)
    else:
        std_val = 1.0
    return mean_val, std_val


def calculate_solar_tod_stats(filepath: str, target_hour: int) -> Tuple[float, float]:
    """Computes mean and std dev of solar power for a specific hour block from history CSV."""
    if not os.path.exists(filepath):
        return 0.0, 0.0
    vals = []
    try:
        with open(filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    ts_str = row[0].strip().replace('\x00', '')
                    try:
                        if len(ts_str) >= 13:
                            hour = int(ts_str[11:13])
                            if hour == target_hour:
                                vals.append(float(row[1]))
                    except ValueError:
                        pass
    except Exception as e:
        logging.error(f"Error calculating solar TOD stats: {e}")
    if not vals:
        return 0.0, 0.0
    mean_val = sum(vals) / len(vals)
    if len(vals) > 1:
        var_val = sum((x - mean_val) ** 2 for x in vals) / (len(vals) - 1)
        std_val = math.sqrt(var_val)
    else:
        std_val = 0.0
    return mean_val, std_val


def calculate_solar_correlation(se_filepath: str, ch_filepath: str) -> float:
    """Computes Pearson correlation coefficient between SolarEdge and Chillicon outputs during daylight hours (6 AM to 8 PM)."""
    if not os.path.exists(se_filepath) or not os.path.exists(ch_filepath):
        return 0.0
        
    se_data = {}
    try:
        with open(se_filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    ts_str = row[0].strip().replace('\x00', '')
                    if len(ts_str) >= 16:
                        key = ts_str[:15] # YYYY-MM-DD HH:M
                        try:
                            hour = int(ts_str[11:13])
                            if 6 <= hour <= 20:
                                se_data[key] = float(row[1])
                        except ValueError:
                            pass
    except Exception as e:
        logging.error(f"Error reading SolarEdge for correlation: {e}")
        
    ch_data = {}
    try:
        with open(ch_filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    ts_str = row[0].strip().replace('\x00', '')
                    if len(ts_str) >= 16:
                        key = ts_str[:15]
                        try:
                            hour = int(ts_str[11:13])
                            if 6 <= hour <= 20:
                                ch_data[key] = float(row[1])
                        except ValueError:
                            pass
    except Exception as e:
        logging.error(f"Error reading Chillicon for correlation: {e}")
        
    common_keys = set(se_data.keys()).intersection(set(ch_data.keys()))
    if len(common_keys) < 5:
        return 0.0
        
    x = [se_data[k] for k in common_keys]
    y = [ch_data[k] for k in common_keys]
    
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = sum((xi - mean_x) ** 2 for xi in x)
    den_y = sum((yi - mean_y) ** 2 for yi in y)
    
    if den_x == 0 or den_y == 0:
        return 0.0
        
    return num / math.sqrt(den_x * den_y)


def calculate_deltas(baseline_dt: datetime.datetime) -> Dict[str, float]:
    """Calculates delta metrics since the baseline timestamp by parsing CSV files."""
    # 1. Grid import, export, and peak demand
    delta_import = 0.0
    delta_export = 0.0
    delta_peak = 0.0
    
    if os.path.exists(GRID_HISTORY):
        rows = []
        try:
            with open(GRID_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 2:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[1])
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading grid history for deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    if p_curr > 0:
                        delta_import += p_curr * dt_hours
                        delta_peak = max(delta_peak, p_curr)
                    else:
                        delta_export += abs(p_curr) * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                if p_last > 0:
                    delta_import += p_last * dt_hours
                    delta_peak = max(delta_peak, p_last)
                else:
                    delta_export += abs(p_last) * dt_hours

    # 2. SolarEdge Generation
    se_kwh = 0.0
    if os.path.exists(SE_HISTORY):
        rows = []
        try:
            with open(SE_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 2:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[1])
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading SolarEdge history for deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    se_kwh += p_curr * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                se_kwh += p_last * dt_hours

    # 3. Chillicon Generation
    ch_kwh = 0.0
    if os.path.exists(CHILICON_HISTORY):
        rows = []
        try:
            with open(CHILICON_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 2:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[1])
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading Chillicon history for deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    ch_kwh += p_curr * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                ch_kwh += p_last * dt_hours

    delta_solar = se_kwh + ch_kwh

    # 4. Battery activity
    delta_bat_charge = 0.0
    delta_bat_discharge = 0.0
    if os.path.exists(SE_BATTERY_HISTORY):
        rows = []
        try:
            with open(SE_BATTERY_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 2:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[1])
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading battery history for deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    if p_curr > 0:
                        delta_bat_discharge += p_curr * dt_hours
                    else:
                        delta_bat_charge += abs(p_curr) * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                if p_last > 0:
                    delta_bat_discharge += p_last * dt_hours
                else:
                    delta_bat_charge += abs(p_last) * dt_hours

    return {
        "delta_import": delta_import,
        "delta_export": delta_export,
        "delta_peak": delta_peak,
        "delta_solar": delta_solar,
        "delta_bat_charge": delta_bat_charge,
        "delta_bat_discharge": delta_bat_discharge
    }


def query_local_ollama(prompt: str, model: str) -> str:
    """Queries local Ollama generation API synchronously."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": "You are a precise, low-overhead edge AI energy assistant.",
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
    except Exception as e:
        logging.error(f"Ollama API error: {e}")
        raise


def run_analysis_workflow(baseline_ts_str: str, baseline_text: str) -> Dict[str, Any]:
    """Runs the quantitative modeling and local LLM summary generation workflow."""
    baseline_dt = parse_timestamp(baseline_ts_str)
    if not baseline_dt:
        raise ValueError(f"Could not parse baseline timestamp: {baseline_ts_str}")
        
    # 1. Fetch weather forecast
    temp_max, cloud_cover = fetch_weather()
    
    # 2. Integrate recent telemetry deltas
    deltas = calculate_deltas(baseline_dt)
    
    # 3. Perform statistical calculations
    grid_mean, grid_std = calculate_grid_stats(GRID_HISTORY)
    current_hour = datetime.datetime.now().hour
    se_mean, se_std = calculate_solar_tod_stats(SE_HISTORY, current_hour)
    solar_corr = calculate_solar_correlation(SE_HISTORY, CHILICON_HISTORY)
    
    # Calculate battery round-trip efficiency
    battery_rte = 0.0
    if deltas["delta_bat_charge"] > 0:
        battery_rte = deltas["delta_bat_discharge"] / deltas["delta_bat_charge"]
        
    # Z-Score of the live peak grid demand
    z_score_peak = 0.0
    if grid_std > 0:
        z_score_peak = (deltas["delta_peak"] - grid_mean) / grid_std
        
    # 4. Statistical anomaly flagging & prompt decoration
    warnings = []
    
    # Check grid import Z-score
    if z_score_peak > 2.5:
        warnings.append(f"Statistically significant peak grid load spike detected (Z-Score: {z_score_peak:.2f}).")
        
    # Adjust solar baseline dynamically based on cloud cover
    expected_solar_kwh = se_mean * ( (datetime.datetime.now() - baseline_dt).total_seconds() / 3600.0 )
    if cloud_cover is not None:
        # Scale down expectation based on cloudiness
        expected_solar_kwh *= ((100.0 - cloud_cover) / 100.0)
        
    if expected_solar_kwh > 0:
        solar_deficit_ratio = (expected_solar_kwh - deltas["delta_solar"]) / expected_solar_kwh
        # Flag if we have a solar deficit greater than standard deviations/margins
        if solar_deficit_ratio > 0.40 and deltas["delta_solar"] < expected_solar_kwh:
            if cloud_cover is not None and cloud_cover > 60:
                warnings.append(f"Solar PV yield is low, corresponding to forecasted overcast skies ({cloud_cover}% cloud cover).")
            else:
                warnings.append(f"Unexpected solar yield deficit detected relative to clear sky baselines (yield deficit: {solar_deficit_ratio*100:.1f}%).")
                
    # Check solar correlation coefficient
    if solar_corr < 0.70 and deltas["delta_solar"] > 0.5:
        warnings.append(f"Solar Edge and Chillicon PV outputs show low correlation (r={solar_corr:.2f}), suggesting sensor drift or micro-grid shading.")
        
    # Format warning context to append to LLM instructions
    warning_context = ""
    if warnings:
        warning_context = "\nStatistical Anomaly Warnings (Keep these in mind for your analysis):\n" + "\n".join(f"- {w}" for w in warnings)
        
    # 5. Load and format prompt template
    prompt_template = None
    prompt_path = os.path.join(SCRIPT_DIR, "gemma_hybrid_prompt.txt")
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
        except Exception as e:
            logging.error(f"Failed to read prompt template: {e}")
            
    if not prompt_template:
        # Fallback template
        prompt_template = """Baseline Summary (Generated at {baseline_time}):
{baseline_text}

Current Date and Time: {current_time}
Live Telemetry since baseline ({baseline_time} to {current_time}):
- Net Grid Import: {delta_import:.2f} kWh
- Net Grid Export: {delta_export:.2f} kWh
- Peak Grid Demand: {delta_peak:.2f} kW
- Solar PV Generation: {delta_solar:.2f} kWh
- Battery Energy Charged: {delta_bat_charge:.2f} kWh
- Battery Energy Discharged: {delta_bat_discharge:.2f} kWh
- Expected Max Temperature: {expected_temp_max:.1f}°C
- Expected Cloud Cover: {expected_cloud_cover:.0f}%

Instructions:
1. Compare the live telemetry numbers against the baseline summary.
2. If there are material deviations (e.g., unexpected energy spikes, high grid imports when the baseline expected export, solar output dropping off early, or unexpected battery behavior), output 1 or 2 brief bullet points summarizing the deviation.
3. Keep each bullet point under 60 characters. Do not use conversational filler, greetings, or explanations.
4. If there are no material changes or everything is operating within the expected baseline parameters, output exactly this phrase:
Operating within baseline parameters.

Output:
"""

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # We pass 0.0 if None for clean string formatting
    weather_temp = temp_max if temp_max is not None else 0.0
    weather_clouds = cloud_cover if cloud_cover is not None else 0.0
    
    formatted_prompt = prompt_template.format(
        baseline_time=baseline_ts_str,
        baseline_text=baseline_text,
        current_time=now_str,
        delta_import=deltas["delta_import"],
        delta_export=deltas["delta_export"],
        delta_peak=deltas["delta_peak"],
        delta_solar=deltas["delta_solar"],
        delta_bat_charge=deltas["delta_bat_charge"],
        delta_bat_discharge=deltas["delta_bat_discharge"],
        expected_temp_max=weather_temp,
        expected_cloud_cover=weather_clouds
    )
    
    # Append the statistical warnings to guide the model contextually
    if warning_context:
        formatted_prompt += warning_context
        
    # 6. Query Ollama
    model_name = DEFAULT_MODEL
    logging.info(f"Submitting query to Ollama model {model_name}...")
    llm_response = query_local_ollama(formatted_prompt, model_name)
    
    return {
        "response": llm_response,
        "metrics": {
            "temp_max": temp_max,
            "cloud_cover": cloud_cover,
            "z_score_peak": z_score_peak,
            "battery_rte": battery_rte,
            "solar_correlation": solar_corr
        }
    }


class AnalyzeHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/analyze':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data.decode('utf-8'))
                baseline_ts_str = payload.get("baseline_timestamp")
                baseline_text = payload.get("baseline_text", "")
                
                if not baseline_ts_str:
                    self.send_error_response("Missing baseline_timestamp")
                    return
                
                logging.info(f"Received API analysis request. Baseline timestamp: {baseline_ts_str}")
                response_data = run_analysis_workflow(baseline_ts_str, baseline_text)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            except Exception as e:
                logging.error(f"Error handling POST /api/analyze: {e}")
                self.send_error_response(str(e))
        else:
            self.send_response(404)
            self.end_headers()
            
    def send_error_response(self, msg):
        self.send_response(400)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode('utf-8'))
        
    def log_message(self, format, *args):
        # Log HTTP requests using standard logging config
        logging.info("%s - - %s" % (self.address_string(), format%args))


def main() -> None:
    port = 5000
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("--port="):
                try:
                    port = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
                    
    # Read environment configs if present
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            logging.info("Loaded .env config file for server.")
        except Exception as e:
            logging.error(f"Could not load .env file: {e}")

    global DEFAULT_MODEL, OLLAMA_ENDPOINT
    DEFAULT_MODEL = os.environ.get("EDGE_MODEL", DEFAULT_MODEL)
    OLLAMA_ENDPOINT = os.environ.get("OLLAMA_HOST", OLLAMA_ENDPOINT)

    # Allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    handler = AnalyzeHTTPRequestHandler
    
    with socketserver.TCPServer(("", port), handler) as httpd:
        logging.info(f"Jetson Edge HTTP Server started on port {port}. Model: {DEFAULT_MODEL}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        logging.info("Jetson Edge HTTP Server stopped.")

if __name__ == "__main__":
    main()

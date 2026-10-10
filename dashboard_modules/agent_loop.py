"""Agentic SQL Tool Execution Loop for microgrid anomaly diagnostics.

Enables local edge AI models (such as Gemma) to generate, execute, and iterate
on SQL queries against the microgrid telemetry SQLite database. Provides structured
tool-use interception (query_db tool) and returns observation records to the model
to construct final diagnostic reports.
"""

import datetime
import json
import logging
import os
import sqlite3
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union

# Configuration
_ollama_host_env: str = os.environ.get("OLLAMA_HOST", "http://192.168.8.103:11434")
OLLAMA_ENDPOINT: str = _ollama_host_env if _ollama_host_env.endswith("/api/generate") else _ollama_host_env.rstrip("/") + "/api/generate"
DEFAULT_MODEL: str = "gemma4-it-q4:latest"
_failed_endpoints_cache: Dict[str, float] = {}

SYSTEM_PROMPT: str = """You are a precise, edge-based AI microgrid analysis agent.
You have access to the SQLite database containing microgrid telemetry tables:
1. grid_history (timestamp TEXT PRIMARY KEY, kw REAL NOT NULL)
2. solaredge_history (timestamp TEXT PRIMARY KEY, pv_kw REAL NOT NULL)
3. solaredge_battery_history (timestamp TEXT PRIMARY KEY, battery_kw REAL NOT NULL, soc REAL NOT NULL)
4. solaredge_flow_history (timestamp TEXT PRIMARY KEY, pv_power_kw REAL NOT NULL, load_power_kw REAL NOT NULL, grid_import_kw REAL NOT NULL, grid_export_kw REAL NOT NULL)
5. chilicon_history (timestamp TEXT PRIMARY KEY, power_kw REAL NOT NULL, lifetime_wh REAL NOT NULL)

To query the database, you MUST output a tool call wrapped in <tool_call> and </tool_call> tags, like this:
<tool_call>{"tool": "query_db", "sql": "SELECT timestamp, kw FROM grid_history WHERE timestamp BETWEEN '2026-06-14T20:00:00' AND '2026-06-14T21:00:00'"}</tool_call>

Once you get the query results, review them, perform any calculations, and output your final descriptive diagnostic summary explaining the anomaly and what might have caused it. Do not use <tool_call> tags in your final answer.
"""


def execute_sql_query(db_path: str, sql: str, analysis_db_path: Optional[str] = None) -> str:
    """Executes a raw SQL query against the SQLite telemetry database safely.

    Only allows SELECT queries to prevent destructive operations.

    Args:
        db_path: Path to the SQLite database file.
        sql: The SQL query string to execute.
        analysis_db_path: Optional path to analysis_history.db to attach if needed.

    Returns:
        A JSON-formatted string of the matching database records,
        or an error message.
    """
    cleaned_sql: str = sql.strip()
    if not cleaned_sql.lower().startswith("select"):
        return "Error: Only SELECT queries are permitted for safety reasons."

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if analysis_history table exists in main DB; if not, attach analysis_db
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_history'")
        if not cursor.fetchone():
            target_adb = analysis_db_path
            if not target_adb:
                candidate = os.path.join(os.path.dirname(db_path), "analysis_history.db")
                if os.path.exists(candidate):
                    target_adb = candidate
            if target_adb and os.path.exists(target_adb):
                try:
                    cursor.execute("ATTACH DATABASE ? AS analysis_db", (target_adb,))
                    cursor.execute("CREATE TEMP VIEW IF NOT EXISTS analysis_history AS SELECT * FROM analysis_db.analysis_history")
                except Exception as attach_err:
                    logging.debug(f"Could not attach analysis DB: {attach_err}")

        cursor.execute(cleaned_sql)
        columns: List[str] = [description[0] for description in cursor.description]
        rows: List[Tuple[Union[str, float, None], ...]] = cursor.fetchall()
        conn.close()

        # Build list of dicts to return as JSON
        results: List[Dict[str, Union[str, float, None]]] = []
        for row in rows:
            results.append(dict(zip(columns, row)))

        # Cap results size to avoid overflowing LLM context (300 records for 16GB Mac Mini headroom)
        if len(results) > 300:
            results = results[:300]
            truncated_msg = {"note": "Results truncated to 300 records.", "data": results}
            return json.dumps(truncated_msg)
        
        return json.dumps(results)
    except sqlite3.Error as err:
        return f"Database Error: {err}"


def query_ollama(
    prompt: str,
    model: str = DEFAULT_MODEL,
    custom_system_prompt: Optional[str] = None
) -> str:
    """Sends a synchronous request to the Ollama endpoint with robust multi-node failover.

    Args:
        prompt: The fully constructed prompt string.
        model: The target model name.
        custom_system_prompt: Optional custom system prompt overriding the default.

    Returns:
        The generated text response.

    Raises:
        IOError: If communication with Ollama fails.
    """
    import socket
    import urllib.error
    import urllib.request

    if custom_system_prompt:
        system_prompt = custom_system_prompt
    else:
        system_prompt = SYSTEM_PROMPT
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "gemma_agent_prompt.txt"
        )
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, "r", encoding="utf-8") as pf:
                    system_prompt = pf.read()
            except Exception as pe:
                logging.error(f"Error reading gemma_agent_prompt.txt: {pe}")

def get_ollama_endpoints() -> List[str]:
    """Returns the ordered list of standard Ollama rotation endpoints with tool-call support."""
    def is_running_on_pi() -> bool:
        try:
            hostname = socket.gethostname().lower()
            return "pi" in hostname or "rainforest" in hostname
        except Exception:
            return False

    endpoints = [
        "http://192.168.8.103:11434/api/generate", # 1. Stevens-Mini-2 (M4 Mac mini 16GB)
        "http://192.168.8.22:11434/api/generate",  # 2. mac-m1-max (Apple Silicon M1 Max 32GB)
        "http://192.168.8.181:11434/api/generate", # 3. 520c (Intel Xeon + RTX 4060 8GB)
        "http://192.168.8.193:11434/api/generate", # 4. ubunto-giga (Secondary GPU)
        "http://192.168.8.82:11434/api/generate"   # 5. i7office (Windows Host)
    ]

    for env_var in ["OLLAMA_HOST", "FALLBACK_OLLAMA_HOST", "LOCAL_OLLAMA_HOST"]:
        val = os.environ.get(env_var)
        if val:
            if not val.endswith("/api/generate"):
                val = val.rstrip("/") + "/api/generate"
            if val not in endpoints:
                endpoints.append(val)

    if not is_running_on_pi():
        local_endpoint = "http://localhost:11434/api/generate"
        if local_endpoint not in endpoints:
            endpoints.append(local_endpoint)

    return endpoints


def call_ollama_with_rotation(
    prompt: str,
    system: Optional[str] = None,
    stream_handler: Optional[Callable[[str], None]] = None,
    model: str = "gemma4-it-q4:latest",
    options: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0
) -> Dict[str, Any]:
    """Queries Ollama with automatic failover across hosts and model variants.

    Rotates sequentially through available cluster endpoints (M4 Mac mini,
    Apple Silicon GPU nodes, auxiliary GPU servers) and tracks temporary failures.

    Args:
        prompt: The input prompt text.
        system: Optional system instruction prompt.
        stream_handler: Optional callback function receiving token chunks.
        model: Target model name.
        options: Inference hyperparameter dictionary (num_ctx, temperature).
        timeout: Socket request timeout in seconds.

    Returns:
        The parsed JSON dictionary from the successful Ollama response.

    Raises:
        IOError: If all candidate hosts and models fail or time out.
    """
    if options is None:
        # Exploit M4 Mac mini 16GB RAM: 16k context window and 2k output tokens
        options = {
            "temperature": 0.25,
            "num_ctx": 16384,
            "num_predict": 2048,
        }

    # Dynamically reload prompt if system is not explicitly passed
    if not system:
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gemma_agent_prompt.txt")
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, "r", encoding="utf-8") as f:
                    system = f.read().strip()
            except Exception as pe:
                logging.error(f"Error reading gemma_agent_prompt.txt: {pe}")

    endpoints = get_ollama_endpoints()

    # Filter out endpoints that failed recently (within 10 minutes)
    import time
    now = time.time()
    active_endpoints = []
    for ep in endpoints:
        failed_at = _failed_endpoints_cache.get(ep, 0.0)
        if now - failed_at > 600.0:
            active_endpoints.append(ep)
    
    # Fallback to try everything if all endpoints are temporarily blocked
    if not active_endpoints:
        active_endpoints = endpoints

    # Build sequence of models to try
    models_to_try = []
    if model:
        models_to_try.append(model)
    fallback_models = [
        "gemma4-it-q4:latest",
        "gemma4-it-q4",
        "gemma4-e2b-q4:latest",
        "gemma4:12b",
        "gemma4-vision-q4:latest"
    ]
    for fm in fallback_models:
        if fm not in models_to_try:
            models_to_try.append(fm)

    last_err = None
    for endpoint in active_endpoints:
        for target_model in models_to_try:
            payload: Dict[str, Any] = {
                "model": target_model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 2048,
                    "num_ctx": 16384
                }
            }
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    endpoint,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=90) as response:
                    resp_bytes = response.read()
                    resp_data = json.loads(resp_bytes.decode("utf-8"))
                    return str(resp_data.get("response", ""))
            except urllib.error.HTTPError as http_err:
                last_err = http_err
                if http_err.code == 404:
                    logging.warning(f"Ollama model {target_model} not found (404) at {endpoint}. Trying fallback models...")
                    continue
                else:
                    logging.error(f"Ollama server at {endpoint} returned HTTP error {http_err.code}: {http_err.reason}")
                    _failed_endpoints_cache[endpoint] = time.time()
                    break
            except Exception as conn_err:
                last_err = conn_err
                _failed_endpoints_cache[endpoint] = time.time()
                logging.warning(f"Failed to connect to Ollama endpoint {endpoint} with model {target_model}: {conn_err}")
                break

    raise IOError(f"Ollama failover failed. All endpoints/models exhausted. Last error: {last_err}")


def run_agentic_sql_loop(
    db_path: str,
    anomaly_type: str,
    peak_kw: float,
    peak_load: float,
    bimodal_ratio: float,
    rte: float,
    grid_mean: float = 0.0,
    grid_std: float = 1.0,
    house_mean: float = 0.0,
    house_std: float = 1.0,
    model: str = DEFAULT_MODEL,
    max_iterations: int = 3
) -> str:
    """Executes the ReAct reasoning loop, resolving SQL tool calls against the database.

    Args:
        db_path: Path to the SQLite microgrid telemetry database.
        anomaly_type: Description of the detected anomaly.
        peak_kw: Peak demand in kilowatts during the anomalous window.
        peak_load: Peak house load in kilowatts during the anomalous window.
        bimodal_ratio: Spectral bimodal ratio metric.
        rte: Battery round-trip efficiency percentage.
        grid_mean: The historical average grid demand.
        grid_std: The historical standard deviation of the grid demand (noise floor).
        house_mean: The historical average house load.
        house_std: The historical standard deviation of the house load.
        model: Model name to use in Ollama.
        max_iterations: Maximum number of tool query loop iterations.

    Returns:
        The final diagnostic summary generated by the agent.
    """
    initial_user_prompt: str = (
        f"An anomaly has been detected on the microgrid:\n"
        f"- Anomaly Type: {anomaly_type}\n"
        f"- Peak Grid Demand: {peak_kw:.3f} kW\n"
        f"- Peak House Load: {peak_load:.3f} kW\n"
        f"- Battery RTE: {rte:.1f}%\n"
        f"- Grid Bimodal Ratio: {bimodal_ratio:.3f}\n"
        f"- Historical Grid Mean: {grid_mean:.3f} kW\n"
        f"- Historical Grid Std Dev (Noise Floor): {grid_std:.3f} kW\n"
        f"- Historical House Load Mean: {house_mean:.3f} kW\n"
        f"- Historical House Load Std Dev: {house_std:.3f} kW\n\n"
        f"Please run a database query using the query_db tool to inspect the historical context "
        f"surrounding this window (e.g. check the timestamps around the peak load or check SolarEdge "
        f"battery SoC levels), analyze the findings, and generate a final deep diagnostic summary."
    )

    # Initialize conversational prompt structure
    conversation_prompt: str = f"User: {initial_user_prompt}\n\n"

    for iteration in range(max_iterations):
        logging.info(f"[Agent Loop] Starting iteration {iteration + 1}...")
        
        try:
            response_text: str = query_ollama(conversation_prompt, model=model)
        except Exception as e:
            logging.error(f"[Agent Loop] Model query error: {e}")
            return f"Agent loop failed due to model error: {e}"

        logging.info(f"[Agent Loop] Model response:\n{response_text}")

        # Check for tool call tags
        start_tag = "<tool_call>"
        end_tag = "</tool_call>"
        if start_tag in response_text and end_tag in response_text:
            # Extract tool call content
            start_idx = response_text.find(start_tag) + len(start_tag)
            end_idx = response_text.find(end_tag)
            tool_json_str = response_text[start_idx:end_idx].strip()

            try:
                tool_data = json.loads(tool_json_str)
                tool_name = tool_data.get("tool")
                sql_query = tool_data.get("sql")

                if tool_name == "query_db" and sql_query:
                    logging.info(f"[Agent Loop] Executing Tool: query_db | SQL: {sql_query}")
                    observation: str = execute_sql_query(db_path, sql_query)
                    logging.info(f"[Agent Loop] Tool Result: {len(observation)} bytes returned.")
                    
                    # Append response and observation to prompt context
                    conversation_prompt += (
                        f"Assistant: {response_text}\n\n"
                        f"System: Observation from query_db: {observation}\n\n"
                    )
                    continue
                else:
                    logging.error(f"[Agent Loop] Unknown tool or missing SQL query: {tool_json_str}")
                    conversation_prompt += (
                        f"Assistant: {response_text}\n\n"
                        f"System: Error: Unknown tool or missing SQL parameters.\n\n"
                    )
            except json.JSONDecodeError:
                logging.error(f"[Agent Loop] Failed to decode tool JSON: {tool_json_str}")
                conversation_prompt += (
                    f"Assistant: {response_text}\n\n"
                    f"System: Error: Invalid JSON in tool call.\n\n"
                )
        else:
            # No tool call, the model has outputted the final answer
            return response_text

    # If maximum iterations exceeded and the last response was still a tool call,
    # run one final completion to get the model's final response using the observations.
    start_tag = "<tool_call>"
    end_tag = "</tool_call>"
    if start_tag in response_text and end_tag in response_text:
        logging.info("[Agent Loop] Max iterations reached with a tool call. Executing final query for summary...")
        try:
            conversation_prompt += (
                f"Assistant: {response_text}\n\n"
                f"System: Maximum query steps reached. Please synthesize your final diagnostic summary "
                f"based on all observations above. Do not output any more <tool_call> tags.\n\n"
            )
            response_text = query_ollama(conversation_prompt, model=model)
        except Exception as e:
            logging.error(f"[Agent Loop] Final model query error: {e}")
            
    return response_text


def get_seasonality_context(
    dt: Optional[datetime.datetime] = None,
    sunrise_str: Optional[str] = None,
    sunset_str: Optional[str] = None,
    daylight_hours: Optional[float] = None
) -> Dict[str, Any]:
    """Generates seasonal and sun-cycle context based on month and daylight hours.

    Categorizes the season, daylight trend, and typical microgrid behavioral patterns
    for the Pacific Northwest (Seattle/Issaquah region).

    Args:
        dt: Reference datetime (defaults to now).
        sunrise_str: Optional sunrise time string (e.g. "07:18").
        sunset_str: Optional sunset time string (e.g. "18:31").
        daylight_hours: Optional calculated daylight hours float.

    Returns:
        Dict with season, month, sun hours, and regional microgrid profiles.
    """
    if dt is None:
        dt = datetime.datetime.now()
    elif isinstance(dt, str):
        try:
            dt = datetime.datetime.fromisoformat(dt.replace(" ", "T"))
        except Exception:
            dt = datetime.datetime.now()

    month = dt.month
    month_name = dt.strftime("%B")

    # Dynamic seasonal sun cycle defaults for Pacific Northwest by month
    seasonal_sun = {
        1: ("07:55", "16:45", 8.8),
        2: ("07:20", "17:30", 10.2),
        3: ("07:15", "19:15", 12.0),
        4: ("06:20", "20:00", 13.7),
        5: ("05:35", "20:45", 15.2),
        6: ("05:11", "21:11", 16.0),
        7: ("05:30", "21:00", 15.5),
        8: ("06:10", "20:20", 14.2),
        9: ("06:55", "19:20", 12.4),
        10: ("07:18", "18:31", 11.2),
        11: ("07:20", "16:40", 9.3),
        12: ("07:54", "16:21", 8.5),
    }
    def_sunrise, def_sunset, def_hours = seasonal_sun.get(month, ("07:18", "18:31", 11.2))

    # Pacific Northwest Season Mapping
    if month in (12, 1, 2):
        season_name = "Winter"
        solar_trend = "Minimal daylight (~8.5-9.5h), low sun angles, and persistent cloud cover restrict solar PV generation."
        load_trend = "Peak heating season (furnace, space heat, lighting); highest household grid reliance and import volume."
        battery_role = "Battery charges minimally from solar; primary role is emergency reserve and morning/evening PSE Flex event dispatch."
    elif month in (3, 4, 5):
        season_name = "Spring"
        solar_trend = "Daylight expanding rapidly (~12-15h); solar PV yield increasing significantly as sun elevation rises."
        load_trend = "Moderate heating loads declining; milder temperatures reduce space heating requirements."
        battery_role = "Transition season; battery begins reaching 100% SoC regularly from afternoon solar surplus."
    elif month in (6, 7, 8):
        season_name = "Summer"
        solar_trend = "Peak solar generation (~15-16h daylight, late sunset ~21:10); highest daily PV production across NW & SW arrays."
        load_trend = "Low baseload demand, with occasional spikes from air conditioning (A/C) cooling cycles on hot afternoons."
        battery_role = "Daily full charge/discharge cycling; heavy generative export ($0.19/kWh) to utility grid."
    else:  # (9, 10, 11)
        season_name = "Autumn / Fall"
        solar_trend = "Daylight rapidly narrowing (~10.5-12.5h), lower sun elevation, and autumnal cloud cover taper solar production."
        load_trend = "Space heating commences as evening temperatures cool; early sunsets shift lighting and appliance loads earlier."
        battery_role = "Midday solar surplus is often insufficient for full battery replenishment; battery assists with evening peak shaving and PSE Flex dispatch."

    return {
        "month": month,
        "month_name": month_name,
        "season": season_name,
        "sunrise": sunrise_str or def_sunrise,
        "sunset": sunset_str or def_sunset,
        "daylight_hours": round(daylight_hours, 1) if daylight_hours is not None else def_hours,
        "solar_trend": solar_trend,
        "load_trend": load_trend,
        "battery_role": battery_role
    }


def get_14day_daily_breakdown_table(db_path: str, analysis_db_path: Optional[str] = None) -> str:
    """Builds a formatted markdown/text table of the 14-day daily metrics from analysis_history.

    Exploits the 16GB Mac Mini context headroom by providing day-by-day telemetry
    directly in the prompt for deeper situational awareness.
    """
    try:
        target_db = db_path
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_history'")
        has_table = cursor.fetchone() is not None
        if not has_table:
            conn.close()
            candidate = analysis_db_path or os.path.join(os.path.dirname(db_path), "analysis_history.db")
            if not os.path.exists(candidate):
                alt = os.path.join(os.path.dirname(db_path), "backups", "analysis_history.db")
                if os.path.exists(alt):
                    candidate = alt
            if os.path.exists(candidate):
                target_db = candidate
            else:
                return "Daily breakdown: No historical records found in analysis_history."
            conn = sqlite3.connect(target_db)
            cursor = conn.cursor()

        cursor.execute("""
            SELECT substr(timestamp, 1, 10) as day,
                   ROUND(SUM(delta_import), 2) as import_kwh,
                   ROUND(SUM(delta_export), 2) as export_kwh,
                   ROUND(MAX(delta_peak), 2) as peak_kw,
                   ROUND(SUM(delta_solar), 2) as solar_kwh,
                   ROUND(SUM(delta_bat_charge), 2) as bat_chg_kwh,
                   ROUND(SUM(delta_bat_discharge), 2) as bat_dis_kwh,
                   ROUND(SUM(delta_se_load), 2) as load_kwh
            FROM analysis_history
            GROUP BY day
            ORDER BY day DESC
            LIMIT 14
        """)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "No daily historical records available."

        lines = [
            "| Date (Day) | Net Import | Net Export | Solar PV | Bat Chg | Bat Dis | Peak kW | House Load | Event Flag |",
            "|---|---|---|---|---|---|---|---|---|"
        ]
        for r in reversed(rows):
            day_str, imp, exp, peak, sol, chg, dis, load = r
            try:
                dt = datetime.datetime.strptime(str(day_str), '%Y-%m-%d')
                day_label = dt.strftime('%m-%d (%a)')
            except Exception:
                day_label = str(day_str)

            dis_val = float(dis or 0.0)
            sol_val = float(sol or 0.0)
            if dis_val > 0.1:
                flag = "⚡ PSE Flex Event"
            elif sol_val > 200.0:
                flag = "☀️ High Solar"
            else:
                flag = "Normal"
            lines.append(
                f"| {day_label} | {float(imp or 0):.1f} kWh | {float(exp or 0):.1f} kWh | {sol_val:.1f} kWh | "
                f"{float(chg or 0):.1f} kWh | {dis_val:.1f} kWh | {float(peak or 0):.1f} kW | {float(load or 0):.1f} kWh | {flag} |"
            )
        return "\n".join(lines)
    except Exception as e:
        logging.warning(f"Failed to generate 14-day breakdown table: {e}")
        return f"Daily breakdown table unavailable: {e}"


def run_14day_agentic_history_loop(
    db_path: str,
    raw_metrics: Dict[str, Any],
    analysis_db_path: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_iterations: int = 5,
    remaining_lines: int = 15
) -> str:
    """Executes an interactive ReAct SQL agent loop for 14-day microgrid history.

    Empowers the local model (e.g. Gemma 4 on the Mac Mini) to query the SQLite database,
    inspect multi-day historical trends and PSE Flex events, incorporate seasonal sun-cycle
    context, and synthesize an engaging homeowner-oriented narrative for Slide 2.

    Args:
        db_path: Path to the telemetry database.
        raw_metrics: Quantitative 14-day metrics calculated by the stager.
        analysis_db_path: Optional path to analysis_history.db.
        model: Model name to use in Ollama.
        max_iterations: Maximum number of tool query loop iterations.
        remaining_lines: Target line budget for the Slide 2 GUI.

    Returns:
        The final diagnostic 14-day history narrative string.
    """
    now = datetime.datetime.now()
    eval_time = raw_metrics.get("timestamp") or now.strftime("%Y-%m-%d %H:%M:%S")

    # Resolve date object for seasonality
    try:
        ref_dt = datetime.datetime.strptime(eval_time, "%Y-%m-%d %H:%M:%S")
    except Exception:
        ref_dt = now

    sunrise_time = raw_metrics.get("sunrise_time", "07:18")
    sunset_time = raw_metrics.get("sunset_time", "18:31")
    daylight_dur = raw_metrics.get("daylight_duration", 11.2)
    season_info = get_seasonality_context(ref_dt, sunrise_time, sunset_time, daylight_dur)

    # 14-day Quantitative metrics extraction
    delta_import = float(raw_metrics.get("history_delta_import", raw_metrics.get("delta_import", 0.0)))
    delta_export = float(raw_metrics.get("history_delta_export", raw_metrics.get("delta_export", 0.0)))
    delta_peak = float(raw_metrics.get("history_delta_peak", raw_metrics.get("delta_peak", 0.0)))
    delta_solar = float(raw_metrics.get("history_delta_solar", raw_metrics.get("delta_solar", 0.0)))
    delta_se_solar = float(raw_metrics.get("history_delta_se_solar", raw_metrics.get("delta_se_solar", 0.0)))
    delta_ch_solar = float(raw_metrics.get("history_delta_ch_solar", raw_metrics.get("delta_ch_solar", 0.0)))
    delta_bat_charge = float(raw_metrics.get("history_delta_bat_charge", raw_metrics.get("delta_bat_charge", 0.0)))
    delta_bat_discharge = float(raw_metrics.get("history_delta_bat_discharge", raw_metrics.get("delta_bat_discharge", 0.0)))
    battery_rte_pct = float(raw_metrics.get("battery_rte_pct", 0.0))
    delta_se_load = float(raw_metrics.get("delta_se_load", 0.0))
    se_load_min = float(raw_metrics.get("se_load_min", 0.0))
    se_load_max = float(raw_metrics.get("se_load_max", 0.0))
    se_load_avg = float(raw_metrics.get("se_load_avg", 0.0))
    history_flex_events = int(raw_metrics.get("history_flex_events", 0))
    history_flex_discharge_kwh = float(raw_metrics.get("history_flex_discharge_kwh", 0.0))
    history_flex_credits = float(raw_metrics.get("history_flex_credits", 0.0))
    history_standard_export_kwh = float(raw_metrics.get("history_standard_export_kwh", 0.0))
    history_standard_credits = float(raw_metrics.get("history_standard_credits", 0.0))

    daily_table = get_14day_daily_breakdown_table(db_path, analysis_db_path=analysis_db_path)

    agent_14d_system_prompt = f"""You are a senior microgrid AI energy analyst with direct SQL access to the home's telemetry database.
Your job is to analyze the microgrid's historical 14-day performance and produce a thoughtful, engaging narrative for the homeowner (Slide 2).
You are running on high-headroom hardware capable of deep multi-step reasoning.

DATABASE TABLES AVAILABLE:
1. analysis_history: Contains periodic historical records with columns:
   - timestamp TEXT (e.g. '2026-10-09 18:00:00')
   - delta_import REAL (kWh imported)
   - delta_export REAL (kWh exported)
   - delta_peak REAL (peak grid demand in kW)
   - delta_solar REAL (total solar kWh)
   - delta_se_solar REAL (SolarEdge NW array kWh)
   - delta_ch_solar REAL (Chillicon SW array kWh)
   - delta_bat_charge REAL (battery kWh charged)
   - delta_bat_discharge REAL (battery kWh discharged, > 0.1 indicates active PSE Flex event dispatch)
   - delta_se_load REAL (household appliance load in kWh)
2. grid_history: High-resolution net household demand samples:
   - timestamp TEXT (ISO format: YYYY-MM-DDTHH:MM:SS)
   - kw REAL (Net kW demand. Positive = import, Negative = export)

TOOL USE:
To query the database, output a tool call wrapped in <tool_call> and </tool_call> tags:
<tool_call>{{"tool": "query_db", "sql": "SELECT substr(timestamp, 1, 13) as hour, MAX(kw) as max_kw, AVG(kw) as avg_kw FROM grid_history GROUP BY hour ORDER BY max_kw DESC LIMIT 10"}}</tool_call>

Once you finish your tool observations, write your final response directly without <tool_call> tags.
"""

    initial_prompt = f"""=== 14-DAY SEASONAL & ENVIRONMENTAL CONTEXT ===
- Location: Pacific Northwest (Seattle / Issaquah area)
- Current Date/Time: {eval_time}
- Season: {season_info['season']} ({season_info['month_name']})
- Daylight Profile: Sunrise {season_info['sunrise']} | Sunset {season_info['sunset']} ({season_info['daylight_hours']} hours daylight)
- Seasonal Solar Dynamic: {season_info['solar_trend']}
- Seasonal Load Dynamic: {season_info['load_trend']}
- Seasonal Battery Role: {season_info['battery_role']}

=== 14-DAY OVERALL QUANTITATIVE TOTALS ===
- Evaluation Window: Past 14 Days (336 Hours)
- Total Grid Import: {delta_import:.2f} kWh
- Total Grid Export: {delta_export:.2f} kWh
- Peak Grid Demand: {delta_peak:.2f} kW
- Total Solar PV Generated: {delta_solar:.2f} kWh
  * Northwest Array (SolarEdge): {delta_se_solar:.2f} kWh
  * Southwest Array (Chillicon): {delta_ch_solar:.2f} kWh
- Battery Energy Charged: {delta_bat_charge:.2f} kWh
- Battery Energy Discharged: {delta_bat_discharge:.2f} kWh
- Battery Round-Trip Efficiency (RTE): {battery_rte_pct:.1f}%
- Home Appliance Load (Approx): {delta_se_load:.2f} kWh
  * Load Power: Min {se_load_min:.2f} kW | Max {se_load_max:.2f} kW | Avg {se_load_avg:.2f} kW
- PSE Flex Event Days: {history_flex_events}
- Battery Discharged during Flex Events: {history_flex_discharge_kwh:.2f} kWh
- Premium Flex Credits Earned ($0.50/kWh): ${history_flex_credits:.2f}
- Standard Grid Export (Generative): {history_standard_export_kwh:.2f} kWh
- Standard Credits Earned ($0.19/kWh): ${history_standard_credits:.2f}

=== 14-DAY DAY-BY-DAY PERFORMANCE TABLE ===
{daily_table}

=== DIURNAL OPERATIONAL PROFILES ===
- Morning Ramp (06:00 - 09:00): Wake-up routine, domestic water heating, lighting, space conditioning.
- Midday Solar Soak (10:00 - 15:00): Peak PV yield across NW & SW arrays; self-consumption, battery replenishment, and generative export.
- Evening Peak & Flex Window (17:00 - 21:00): Dinner cooking, entertainment, cooling/heating cycling; utility peak period where PSE Flex dispatches battery at $0.50/kWh.
- Overnight Baseload (22:00 - 05:00): Low steady draw (~300-600W) for refrigeration, networking, standby equipment.

=== INSTRUCTIONS FOR YOUR ANALYSIS ===
1. You may execute queries with query_db to check specific hourly profiles or inspect grid_history samples.
2. Synthesize an intelligent, cohesive, homeowner-friendly narrative for Slide 2:
   - Ground the performance in the current {season_info['month_name']} {season_info['season']} solar window ({season_info['daylight_hours']}h daylight, sunset {season_info['sunset']}), explaining how sun angle and daylight shifts shaped PV production and grid import requirements.
   - Analyze the two-week trajectory: compare week 1 vs week 2, highlight the best and worst solar days from the table, and explain what drove high consumption or peak spikes.
   - Detail the battery's cycling and financial economics: discuss battery health (RTE {battery_rte_pct:.1f}%), highlight the PSE Flex event days where the battery discharged ({history_flex_discharge_kwh:.2f} kWh earning ${history_flex_credits:.2f} at $0.50/kWh), and contrast this with standard generative export (${history_standard_credits:.2f} at $0.19/kWh).
   - Write cleanly and clearly in plain text.
   - Do NOT mention EV or EV charging.
   - Do NOT use markdown code blocks, bold asterisks (**), or bullet lists. Keep it within {remaining_lines} lines of clear flowing paragraphs.
"""

    conversation_prompt = f"User: {initial_prompt}\n\n"
    response_text = ""

    for iteration in range(max_iterations):
        logging.info(f"[14d Agent Loop] Iteration {iteration + 1}...")
        try:
            response_text = query_ollama(
                conversation_prompt,
                model=model,
                custom_system_prompt=agent_14d_system_prompt
            )
        except Exception as e:
            logging.error(f"[14d Agent Loop] Model query error: {e}")
            return f"14-day agent analysis failed: {e}"

        logging.info(f"[14d Agent Loop] Response:\n{response_text}")

        # Check for tool call tags
        start_tag = "<tool_call>"
        end_tag = "</tool_call>"
        if start_tag in response_text and end_tag in response_text:
            start_idx = response_text.find(start_tag) + len(start_tag)
            end_idx = response_text.find(end_tag)
            tool_json_str = response_text[start_idx:end_idx].strip()

            try:
                tool_data = json.loads(tool_json_str)
                tool_name = tool_data.get("tool")
                sql_query = tool_data.get("sql")

                if tool_name == "query_db" and sql_query:
                    logging.info(f"[14d Agent Loop] Executing Tool: query_db | SQL: {sql_query}")
                    observation = execute_sql_query(db_path, sql_query, analysis_db_path=analysis_db_path)
                    logging.info(f"[14d Agent Loop] Tool Result: {len(observation)} bytes.")
                    conversation_prompt += (
                        f"Assistant: {response_text}\n\n"
                        f"System: Observation from query_db: {observation}\n\n"
                    )
                    continue
                else:
                    conversation_prompt += (
                        f"Assistant: {response_text}\n\n"
                        f"System: Error: Unknown tool or missing SQL parameters.\n\n"
                    )
            except json.JSONDecodeError:
                conversation_prompt += (
                    f"Assistant: {response_text}\n\n"
                    f"System: Error: Invalid JSON in tool call.\n\n"
                )
        else:
            return response_text

    # Final completion if last turn was a tool call
    start_tag = "<tool_call>"
    end_tag = "</tool_call>"
    if start_tag in response_text and end_tag in response_text:
        logging.info("[14d Agent Loop] Max iterations reached. Prompting for final synthesis...")
        try:
            conversation_prompt += (
                f"Assistant: {response_text}\n\n"
                f"System: Maximum query steps reached. Please synthesize your final homeowner narrative "
                f"based on all observations above. Do not output any more <tool_call> tags.\n\n"
            )
            response_text = query_ollama(
                conversation_prompt,
                model=model,
                custom_system_prompt=agent_14d_system_prompt
            )
        except Exception as e:
            logging.error(f"[14d Agent Loop] Final model query error: {e}")

    return response_text

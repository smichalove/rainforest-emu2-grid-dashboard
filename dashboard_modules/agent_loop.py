"""Agentic SQL Tool Execution Loop for microgrid anomaly diagnostics.

Enables local edge AI models (such as Gemma) to generate, execute, and iterate
on SQL queries against the microgrid telemetry SQLite database. Provides structured
tool-use interception (query_db tool) and returns observation records to the model
to construct final diagnostic reports.
"""

import json
import logging
import os
import sqlite3
import urllib.request
from typing import Any, Dict, List, Tuple, Union

# Configuration
_ollama_host_env: str = os.environ.get("OLLAMA_HOST", "http://nvagent:11434")
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


def execute_sql_query(db_path: str, sql: str) -> str:
    """Executes a raw SQL query against the SQLite telemetry database safely.

    Only allows SELECT queries to prevent destructive operations.

    Args:
        db_path: Path to the SQLite database file.
        sql: The SQL query string to execute.

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
        cursor.execute(cleaned_sql)
        columns: List[str] = [description[0] for description in cursor.description]
        rows: List[Tuple[Union[str, float, None], ...]] = cursor.fetchall()
        conn.close()

        # Build list of dicts to return as JSON
        results: List[Dict[str, Union[str, float, None]]] = []
        for row in rows:
            results.append(dict(zip(columns, row)))

        # Cap results size to avoid overflowing LLM context
        if len(results) > 50:
            results = results[:50]
            truncated_msg = {"note": "Results truncated to 50 records.", "data": results}
            return json.dumps(truncated_msg)
        
        return json.dumps(results)
    except sqlite3.Error as err:
        return f"Database Error: {err}"


def query_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Sends a synchronous request to the Ollama endpoint with robust multi-node failover.

    Args:
        prompt: The fully constructed prompt string.
        model: The target model name.

    Returns:
        The generated text response.

    Raises:
        IOError: If communication with Ollama fails.
    """
    import socket
    import urllib.error
    import urllib.request

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

    # Helper to check if running on the Pi kiosk
    def is_running_on_pi() -> bool:
        try:
            hostname = socket.gethostname().lower()
            return "pi" in hostname or "rainforest" in hostname
        except Exception:
            return False

    # Build sequential rotation endpoints
    endpoints = [
        "http://192.168.8.45:11434/api/generate",  # 1. nvagent (Primary dedicated GPU)
        "http://192.168.8.193:11434/api/generate", # 2. ubunto-giga (Secondary GPU)
        "http://192.168.8.68:11434/api/generate",  # 3. nvjetson (Data/Math Node)
        "http://192.168.8.82:11434/api/generate"   # 4. i7office (Windows DB Host)
    ]

    # Add env configurations dynamically if different
    for env_var in ["OLLAMA_HOST", "FALLBACK_OLLAMA_HOST", "LOCAL_OLLAMA_HOST"]:
        val = os.environ.get(env_var)
        if val:
            if not val.endswith("/api/generate"):
                val = val.rstrip("/") + "/api/generate"
            if val not in endpoints:
                endpoints.append(val)

    # Exclude localhost on Pi, otherwise append it at the end
    if not is_running_on_pi():
        local_endpoint = "http://localhost:11434/api/generate"
        if local_endpoint not in endpoints:
            endpoints.append(local_endpoint)

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
        "gemma2:2b",
        "gemma2:9b",
        "gemma2-edge:latest"
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
                    "temperature": 0.1,
                    "num_predict": 1024,
                    "num_ctx": 4096
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

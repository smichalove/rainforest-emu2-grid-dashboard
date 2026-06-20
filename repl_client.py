#!/usr/bin/env python3
"""Interactive command-line interface (REPL) client for a local model server.

This script allows developers to run a conversational session with a local VLM
server directly from the terminal. It includes support for text-only prompts
as well as image-rich multimodal inputs via a '/image <path>' shortcut.
It parses local telemetry databases and CSVs from the Mac's local sync directory
to provide the VLM server with contextual RAG data for the past 48 hours.
It also supports inline '/note <message>' commands to log appliance events.
This implementation uses only Python standard libraries (no external dependencies).
"""

import base64
import datetime
import json
import os
import re
import readline
import signal
import sqlite3
import sys
import types
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

# Load configurations from environment variables or .env file.
def load_env_file(dotenv_path: str = ".env") -> None:
    """Reads a .env file if it exists and updates os.environ.

    Args:
        dotenv_path: Path to the .env file.
    """
    if os.path.exists(dotenv_path):
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key:
                        os.environ[key] = val
        except Exception:
            pass


load_env_file()

# Global configuration constants
SERVER_URL: str = os.getenv("LOCAL_SERVER_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma4-it-q4:latest")
SYNC_DIR: str = os.getenv("RAINFOREST_SYNC_DIR", os.path.expanduser("~/rainforest_db"))
DEFAULT_TEMPERATURE: float = 0.2
DEFAULT_MAX_NEW_TOKENS: int = 4096
TELEMETRY_WINDOW_HOURS: int = 48


def parse_time_str(ts_str: str) -> Optional[datetime.datetime]:
    """Robust parser for datetime strings of varying formats.

    Args:
        ts_str: The timestamp string to parse.

    Returns:
        A datetime object if parsing was successful, or None.
    """
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


def encode_image_to_base64(file_path: str) -> Optional[str]:
    """Reads and encodes an image file to a base64 string.

    Args:
        file_path: Absolute or relative path to the image file.

    Returns:
        The base64 encoded string if successful, or None if the file is
        missing or invalid.
    """
    if not os.path.exists(file_path):
        print(f"[Error] Image file not found: {file_path}")
        return None
    try:
        with open(file_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode("utf-8")
    except Exception as e:
        print(f"[Error] Failed to read image: {e}")
        return None


def load_telemetry_table(sync_dir: str, window_hours: int = 48) -> str:
    """Loads and aggregates local microgrid telemetry logs into a markdown table.

    Args:
        sync_dir: Path to the local databases and CSV logs directory.
        window_hours: Number of hours in the past to load.

    Returns:
        A formatted markdown table representing the hourly data blocks.
    """
    now_dt: datetime.datetime = datetime.datetime.now()
    start_dt: datetime.datetime = now_dt - datetime.timedelta(hours=window_hours)
    start_hour_dt: datetime.datetime = start_dt.replace(minute=0, second=0, microsecond=0)
    
    # Generate the hourly keys
    target_hours: List[datetime.datetime] = [
        start_hour_dt + datetime.timedelta(hours=i) for i in range(window_hours + 1)
    ]
    hour_keys: List[str] = [dt.strftime("%Y-%m-%d %H:00") for dt in target_hours]
    
    # Initialize the data map
    data: Dict[str, Dict[str, List[float]]] = {
        hk: {
            "grid": [],
            "se": [],
            "ch": [],
            "bat_power": [],
            "bat_soc": [],
            "load": []
        }
        for hk in hour_keys
    }
    
    # 1. Fetch grid history from SQLite
    grid_db_path: str = os.path.join(sync_dir, "grid_history.db")
    if os.path.exists(grid_db_path):
        try:
            conn = sqlite3.connect(grid_db_path)
            cursor = conn.cursor()
            cutoff_str: str = start_hour_dt.isoformat()
            cursor.execute(
                "SELECT timestamp, kw FROM grid_history WHERE timestamp >= ? ORDER BY timestamp ASC",
                (cutoff_str,)
            )
            for row in cursor.fetchall():
                ts: Optional[datetime.datetime] = parse_time_str(row[0])
                if ts:
                    hk: str = ts.strftime("%Y-%m-%d %H:00")
                    if hk in data:
                        data[hk]["grid"].append(float(row[1]))
            conn.close()
        except Exception as e:
            print(f"[Warning] Failed to query grid database: {e}")

    # Helper function to parse CSV files safely
    def parse_csv_into_data(file_name: str, keys: List[str], col_map: Dict[str, int]) -> None:
        file_path: str = os.path.join(sync_dir, file_name)
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or "," not in line:
                            continue
                        parts: List[str] = line.split(",")
                        ts: Optional[datetime.datetime] = parse_time_str(parts[0])
                        if ts:
                            hk: str = ts.strftime("%Y-%m-%d %H:00")
                            if hk in data:
                                for key_name, col_idx in col_map.items():
                                    if len(parts) > col_idx:
                                        try:
                                            val: float = float(parts[col_idx])
                                            data[hk][key_name].append(val)
                                        except ValueError:
                                            pass
            except Exception as e:
                print(f"[Warning] Failed to read {file_name}: {e}")

    # 2. Parse SolarEdge CSV
    parse_csv_into_data("solaredge_history.csv", hour_keys, {"se": 1})
    
    # 3. Parse Chillicon CSV
    parse_csv_into_data("chilicon_history.csv", hour_keys, {"ch": 1})
    
    # 4. Parse battery state CSV
    parse_csv_into_data("solaredge_battery_history.csv", hour_keys, {"bat_power": 1, "bat_soc": 2})
    
    # 5. Parse flow power CSV
    parse_csv_into_data("solaredge_flow_history.csv", hour_keys, {"load": 2})

    # Render markdown table rows
    rows_markdown: List[str] = [
        "| Hour | Net Grid (kW) | Solar PV (kW) | Battery SoC | Battery Power (kW) | House Load (kW) |",
        "|---|---|---|---|---|---|",
    ]
    
    for hk in hour_keys:
        grid_vals = data[hk]["grid"]
        avg_grid = sum(grid_vals) / len(grid_vals) if grid_vals else 0.0
        
        se_vals = data[hk]["se"]
        avg_se = sum(se_vals) / len(se_vals) if se_vals else 0.0
        
        ch_vals = data[hk]["ch"]
        avg_ch = sum(ch_vals) / len(ch_vals) if ch_vals else 0.0
        avg_solar = avg_se + avg_ch
        
        bat_soc_vals = data[hk]["bat_soc"]
        avg_soc = sum(bat_soc_vals) / len(bat_soc_vals) if bat_soc_vals else 0.0
        
        bat_pow_vals = data[hk]["bat_power"]
        avg_bat_pow = sum(bat_pow_vals) / len(bat_pow_vals) if bat_pow_vals else 0.0
        
        load_vals = data[hk]["load"]
        if load_vals:
            avg_load = sum(load_vals) / len(load_vals)
        else:
            # Fallback to physical load balance formula if direct log is missing
            avg_load = max(0.0, avg_grid + avg_solar + avg_bat_pow)
            
        rows_markdown.append(
            f"| {hk} | {avg_grid:.3f} | {avg_solar:.3f} | {avg_soc:.1f}% | {avg_bat_pow:.3f} | {avg_load:.3f} |"
        )
        
    return "\n".join(rows_markdown)


def load_annotations(sync_dir: str) -> List[Dict[str, str]]:
    """Loads existing user annotations from the sync folder database.

    Args:
        sync_dir: Path to the sync directory.

    Returns:
        A list of annotation dictionaries.
    """
    path: str = os.path.join(sync_dir, "user_annotations.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_annotations(sync_dir: str, annotations: List[Dict[str, str]]) -> None:
    """Atomically saves the list of annotations to the JSON database.

    Args:
        sync_dir: Path to the sync directory.
        annotations: The list of annotation objects to serialize.
    """
    path: str = os.path.join(sync_dir, "user_annotations.json")
    temp_path: str = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(annotations, f, indent=2)
        os.replace(temp_path, path)
    except Exception as e:
        print(f"[Error] Failed to write user annotations database: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def infer_note_timestamp(current_text: str, previous_text: str = "") -> str:
    """Infers the timestamp for a note based on temporal clues in dialogue.

    Args:
        current_text: The user's current prompt.
        previous_text: The user's previous prompt.

    Returns:
        A string representing the inferred timestamp in 'YYYY-MM-DD HH:MM:00' format.
    """
    combined_text: str = (current_text + " " + previous_text).lower()
    
    # 1. Deduce date (supporting "yesterday" or fallback to "today")
    target_date: datetime.date = datetime.date.today()
    if "yesterday" in combined_text:
        target_date = datetime.date.today() - datetime.timedelta(days=1)
        
    # 2. Deduce time (look for HH.MM or HH:MM 24-hour patterns)
    now: datetime.datetime = datetime.datetime.now()
    hour: int = now.hour
    minute: int = now.minute
    
    # Match patterns like 13.30, 13:30, 19.00, 19:00, etc.
    time_match = re.search(r'\b(\d{1,2})[.:](\d{2})\b', combined_text)
    if time_match:
        h = int(time_match.group(1))
        m = int(time_match.group(2))
        if 0 <= h < 24 and 0 <= m < 60:
            hour = h
            minute = m
                
    dt: datetime.datetime = datetime.datetime.combine(target_date, datetime.time(hour, minute))
    return dt.strftime("%Y-%m-%d %H:%M:00")


def sigint_handler(signum: int, frame: Optional[types.FrameType]) -> None:
    """Handles SIGINT (Ctrl-C) to exit the client gracefully.

    Args:
        signum: The signal number (typically SIGINT).
        frame: The current execution frame object or None.
    """
    print("\nExiting...")
    sys.exit(0)


def log_chat_message(sync_dir: str, role: str, content: str) -> None:
    """Logs a single chat message to a persistent JSONL log file for later analysis.

    Args:
        sync_dir: Path to the sync directory where the log file is stored.
        role: The role of the speaker ('user' or 'assistant').
        content: The text content of the message.
    """
    log_path: str = os.path.join(sync_dir, "repl_chat_log.jsonl")
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "role": role,
        "content": content
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"[Warning] Failed to log chat message: {e}")


def run_repl() -> None:
    """Runs the interactive Read-Eval-Print Loop (REPL) CLI chat client.

    Maintains chat memory, aggregates the past 48-hour local telemetry context,
    loads annotations, handles image inputs, and queries the local server.
    """
    print("==================================================")
    print("      nvagent - Context-Aware Chat Client")
    print("==================================================")
    print("Instructions:")
    print("  * Type your prompt and press Enter.")
    print("  * To include an image, start your message with:")
    print("    /image path/to/photo.jpg Your prompt here")
    print("  * To save a note on telemetry, append or prefix:")
    print("    /note that was the kettle turning on")
    print("  * To paste multiline text/logs, type '/paste' and press Enter.")
    print("  * Type 'exit' or 'quit' to close the client.")
    print(f"  * Targeting Ollama: {SERVER_URL} ({OLLAMA_MODEL})")
    print(f"  * Sync Telemetry Path: {SYNC_DIR}")
    print("==================================================")
    print()

    # Register OS-level signal handler for SIGINT (Ctrl-C) to handle libedit/readline correctly
    signal.signal(signal.SIGINT, sigint_handler)

    session = requests.Session() if 'requests' in sys.modules else None
    chat_history: List[Dict[str, str]] = []
    previous_user_input: str = ""

    while True:
        try:
            user_input: str = input("Prompt > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Exiting...")
            break

        images_base64: List[str] = []
        prompt_text: str = user_input
        note_text: Optional[str] = None

        # Check for /summary command
        if user_input.lower().strip() == "/summary":
            print("Analyzing all historical annotations and chat logs to build a summary...")
            annotations = load_annotations(SYNC_DIR)
            
            chat_logs: List[Dict[str, str]] = []
            log_path: str = os.path.join(SYNC_DIR, "repl_chat_log.jsonl")
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            chat_logs.append(json.loads(line.strip()))
                except Exception:
                    pass
            
            compilation: List[str] = []
            compilation.append("=== ALL HISTORICAL ANNOTATIONS ===")
            if annotations:
                for ann in annotations:
                    compilation.append(f"- [{ann.get('timestamp')}]: {ann.get('annotation')}")
            else:
                compilation.append("No annotations found.")
                
            compilation.append("\n=== ALL PAST CHAT LOGS ===")
            if chat_logs:
                for entry in chat_logs[-100:]:
                    compilation.append(f"- [{entry.get('timestamp')}] {entry.get('role').upper()}: {entry.get('content')}")
            else:
                compilation.append("No past chat logs found.")
                
            compilation_str: str = "\n".join(compilation)
            prompt_text = f"""Please summarize all the historical annotations and past chat logs provided below.
Focus on identifying key appliance signatures (e.g., kettle, hifi, pressure washer), model events, or hardware usage details.
Be concise, organized, and homeowner-oriented.

{compilation_str}"""
        else:
            # Check for /paste or /multiline command anywhere in the input
            paste_match = re.search(r'\b/(paste|multiline)\b', user_input, re.IGNORECASE)
            if paste_match:
                # Extract text before and after the trigger word to use as initial context
                trigger: str = paste_match.group(0)
                trigger_idx: int = user_input.lower().find(trigger.lower())
                before_text: str = user_input[:trigger_idx].strip()
                after_text: str = user_input[trigger_idx + len(trigger):].strip()
                
                initial_parts: List[str] = []
                if before_text:
                    initial_parts.append(before_text)
                if after_text:
                    initial_parts.append(after_text)
                initial_text: str = " ".join(initial_parts)
                
                print("[Multiline Mode] Paste text. Type '/end' on a separate line to finish and send.")
                multiline_lines = []
                if initial_text:
                    multiline_lines.append(initial_text)
                
                # Temporarily restore default SIGINT handler to catch KeyboardInterrupt in input()
                old_handler = signal.signal(signal.SIGINT, signal.SIG_DFL)
                try:
                    while True:
                        try:
                            line = input("... ")
                        except EOFError:
                            break
                        if line.strip() == "/end":
                            break
                        multiline_lines.append(line)
                except KeyboardInterrupt:
                    print("\n[Cancelled multiline input]")
                    multiline_lines = []
                finally:
                    # Restore the custom exit signal handler
                    signal.signal(signal.SIGINT, sigint_handler)

                prompt_text = "\n".join(multiline_lines).strip()
                if not prompt_text:
                    continue

            # Check for /note extraction
            note_match = re.search(r'/note\s+(.*)$', user_input, re.IGNORECASE)
            if note_match:
                note_text = note_match.group(1).strip()
                # Remove the note trigger and description from the text sent to the VLM
                prompt_text = user_input.replace(note_match.group(0), "").strip()
                # Clean up double spacing
                prompt_text = re.sub(r'\s+', ' ', prompt_text)
                
                # Infer timestamp and save to JSON log
                inferred_ts: str = infer_note_timestamp(user_input, previous_user_input)
                annotations = load_annotations(SYNC_DIR)
                annotations.append({
                    "timestamp": inferred_ts,
                    "annotation": note_text
                })
                save_annotations(SYNC_DIR, annotations)
                print(f"[Success] Logged annotation: \"{note_text}\" at [{inferred_ts}]")
                
                # If the user only typed the note command, skip sending an empty prompt to VLM
                if not prompt_text:
                    previous_user_input = user_input
                    continue

            # Check for image command shortcut: /image <path> anywhere in the input
            image_match = re.search(r'/image\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))', prompt_text)
            if image_match:
                img_path = image_match.group(1) or image_match.group(2) or image_match.group(3)
                # Remove the /image command from the prompt text
                prompt_text = prompt_text.replace(image_match.group(0), "").strip()
                prompt_text = re.sub(r'\s+', ' ', prompt_text)
                
                if not prompt_text:
                    prompt_text = "Describe this image."

                print(f"[Loading image]: {img_path}...")
                b64_str = encode_image_to_base64(img_path)
                if b64_str:
                    images_base64.append(b64_str)
                    print("[Success] Image successfully loaded and attached to request payload.")
                else:
                    continue

        # Convert literal \n sequences (backslash + n) to actual newlines
        prompt_text = prompt_text.replace("\\n", "\n")

        # Get recent telemetry summaries and annotations
        telemetry_table = load_telemetry_table(SYNC_DIR, TELEMETRY_WINDOW_HOURS)
        annotations_list = load_annotations(SYNC_DIR)
        
        # Filter annotations to the active 48-hour telemetry window
        now_dt: datetime.datetime = datetime.datetime.now()
        cutoff_dt: datetime.datetime = now_dt - datetime.timedelta(hours=TELEMETRY_WINDOW_HOURS)
        recent_annotations: List[Dict[str, str]] = []
        for ann in annotations_list:
            ann_ts = parse_time_str(ann["timestamp"])
            if ann_ts and ann_ts >= cutoff_dt:
                recent_annotations.append(ann)
        
        if recent_annotations:
            annotations_str = "\n".join(
                [f"- [{ann['timestamp']}]: {ann['annotation']}" for ann in recent_annotations]
            )
        else:
            annotations_str = "No existing annotations found in this 48-hour window."

        # Format system prompt context
        system_context = f"""You are a helpful Edge AI microgrid assistant analyzing electrical telemetry data for Steven's house.
The grid import and export values, Solar PV yield, battery state-of-charge (SoC), and charging rates are monitored.

=== 48-HOUR TELEMETRY DATA ===
{telemetry_table}

=== USER ANNOTATIONS ===
{annotations_str}

=== DATABASE & FILE SCHEMA CONTEXT ===
- grid_history.db contains a SQLite table `grid_history` with columns: `timestamp` (TEXT, ISO format) and `kw` (REAL).
- solaredge_history.csv: `timestamp` (TEXT), `pv_kw` (REAL).
- solaredge_battery_history.csv: `timestamp` (TEXT), `battery_kw` (REAL), `soc` (REAL).
- solaredge_flow_history.csv: `timestamp` (TEXT), `grid_power_kw` (REAL), `load_power_kw` (REAL).
- chilicon_history.csv: `timestamp` (TEXT), `power_kw` (REAL), `lifetime_wh` (REAL).

=== INSTRUCTIONS ===
1. Analyze the data around specific times if asked (e.g. "peak around 13:30 today" or "yesterday at 19:00").
2. Connect user queries to the data rows and existing annotations.
3. If asked, write SQLite or scripting code using the exact schema context defined above.
4. Be concise, friendly, and homeowner-oriented.
"""

        # Build structured message list for Ollama's chat API
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_context}
        ]
        
        # Add conversation history
        messages.extend(chat_history)
        
        # Add current user prompt
        messages.append({"role": "user", "content": prompt_text})

        # Prepare request payload for local Ollama chat API on nvagent
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": DEFAULT_TEMPERATURE,
                "num_predict": DEFAULT_MAX_NEW_TOKENS,
                "num_ctx": 8192
            }
        }

        print("Waiting for response...")
        
        req = urllib.request.Request(
            SERVER_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=120.0) as response:
                result = json.loads(response.read().decode("utf-8"))
                response_thinking = result.get("message", {}).get("thinking", "").strip()
                response_text = result.get("message", {}).get("content", "").strip()
                
                if response_thinking:
                    print("\n[Thinking Process]")
                    print(response_thinking)
                    print("-" * 50)
                
                print("\nResponse:")
                if response_text:
                    print(response_text)
                else:
                    print("<Empty response content>")
                print()
                
                if result.get("done_reason") == "length":
                    print("[Warning] The response was truncated because it reached the token limit.")
                    print()
                
                # Update history using role-based keys matching Ollama chat API
                chat_history.append({"role": "user", "content": prompt_text})
                stored_response = response_text if response_text else (f"Thinking: {response_thinking}" if response_thinking else "")
                chat_history.append({"role": "assistant", "content": stored_response})
                if len(chat_history) > 10:  # Keep last 5 rounds of conversation
                    chat_history = chat_history[-10:]
                
                # Log the conversation history to persistent storage for later analysis
                log_chat_message(SYNC_DIR, "user", prompt_text)
                log_chat_message(SYNC_DIR, "assistant", stored_response)
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
                print(f"\n[Error] Server returned HTTP {e.code}: {error_body}\n")
            except Exception:
                print(f"\n[Error] Server returned HTTP {e.code}: {e.reason}\n")
        except urllib.error.URLError as e:
            print(f"\n[Error] Failed to connect to server at {SERVER_URL}: {e.reason}\n")
        except Exception as e:
            print(f"\n[Error] An unexpected error occurred: {e}\n")

        previous_user_input = user_input


if __name__ == "__main__":
    run_repl()

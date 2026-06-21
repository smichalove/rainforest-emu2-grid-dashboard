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
import shutil
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
SERVER_URL: str = os.getenv("LOCAL_SERVER_URL", "http://192.168.8.45:11434/api/chat")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma4-it-q4:latest")
SYNC_DIR: str = os.getenv("RAINFOREST_SYNC_DIR", "/Users/treven/rainforest_db")
DEFAULT_TEMPERATURE: float = 0.2
DEFAULT_MAX_NEW_TOKENS: int = 4096
TELEMETRY_WINDOW_HOURS: int = 168


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


def load_system_prompt(file_name: str = "repl_system_prompt.txt") -> str:
    """Loads the system prompt template from an external file on disk.

    Args:
        file_name: The filename of the prompt template (e.g., 'repl_system_prompt.txt').

    Returns:
        The raw string content of the system prompt template.
    """
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    file_path: str = os.path.join(script_dir, file_name)
    if not os.path.exists(file_path):
        file_path = file_name

    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"[Warning] Failed to read prompt template: {e}")

    # Fallback prompt in case the file cannot be read/accessed
    return (
        "You are a helpful Edge AI microgrid assistant analyzing electrical telemetry data for Steven's house.\n"
        "The grid import and export values, Solar PV yield, battery state-of-charge (SoC), and charging rates are monitored.\n"
        "=== {telemetry_window_hours}-HOUR TELEMETRY DATA ===\n"
        "{telemetry_table}\n"
        "=== USER ANNOTATIONS ===\n"
        "{annotations_str}\n"
    )


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


def build_local_database(sync_dir: str) -> str:
    """Builds a local database containing all synced CSV tables and grid history.

    Copies the raw grid_history.db and migrates the SolarEdge, battery, flow,
    and Chilicon CSV records into it.

    Args:
        sync_dir: The directory containing synced telemetry CSVs and grid_history.db.

    Returns:
        The path to the local unified SQLite database.
    """
    src_db: str = os.path.join(sync_dir, "grid_history.db")
    dest_db: str = os.path.join(sync_dir, "local_repl.db")

    # Copy raw database if it exists
    if os.path.exists(src_db):
        try:
            shutil.copy2(src_db, dest_db)
        except Exception as e:
            print(f"[Warning] Failed to copy grid_history.db to local_repl.db: {e}")
            if not os.path.exists(dest_db):
                # Try to initialize empty
                conn = sqlite3.connect(dest_db)
                conn.close()
    else:
        # Create empty db
        try:
            conn = sqlite3.connect(dest_db)
            conn.close()
        except Exception as e:
            print(f"[Error] Failed to initialize local_repl.db: {e}")
            return src_db  # Fallback

    try:
        conn = sqlite3.connect(dest_db)
        cursor = conn.cursor()

        # Initialize grid_history table just in case it didn't exist or database was blank
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS grid_history (
                timestamp TEXT PRIMARY KEY,
                kw REAL NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_grid_timestamp ON grid_history(timestamp)")

        # Helper to migrate CSV to table
        def migrate_csv_to_table(
            csv_name: str, create_sql: str, insert_sql: str, index_sql: str, col_indices: List[int]
        ) -> None:
            csv_path: str = os.path.join(sync_dir, csv_name)
            if not os.path.exists(csv_path):
                return
            cursor.execute(create_sql)
            cursor.execute(index_sql)
            rows: List[Tuple[str, ...]] = []
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or "," not in line:
                            continue
                        parts = line.split(",")
                        ts = parts[0].strip()
                        try:
                            # Extract columns
                            row_vals = [ts]
                            for idx in col_indices:
                                row_vals.append(float(parts[idx]))
                            rows.append(tuple(row_vals))
                        except (ValueError, IndexError):
                            continue
            except Exception as e:
                print(f"[Warning] Failed to read {csv_name} during migration: {e}")
                return

            if rows:
                cursor.executemany(insert_sql, rows)

        # 1. Migrate SolarEdge PV History
        migrate_csv_to_table(
            "solaredge_history.csv",
            "CREATE TABLE IF NOT EXISTS solaredge_history (timestamp TEXT PRIMARY KEY, pv_kw REAL NOT NULL)",
            "INSERT OR IGNORE INTO solaredge_history (timestamp, pv_kw) VALUES (?, ?)",
            "CREATE INDEX IF NOT EXISTS idx_se_timestamp ON solaredge_history(timestamp)",
            [1]
        )

        # 2. Migrate SolarEdge Battery History
        migrate_csv_to_table(
            "solaredge_battery_history.csv",
            "CREATE TABLE IF NOT EXISTS solaredge_battery_history (timestamp TEXT PRIMARY KEY, battery_kw REAL NOT NULL, soc REAL NOT NULL)",
            "INSERT OR IGNORE INTO solaredge_battery_history (timestamp, battery_kw, soc) VALUES (?, ?, ?)",
            "CREATE INDEX IF NOT EXISTS idx_se_bat_timestamp ON solaredge_battery_history(timestamp)",
            [1, 2]
        )

        # 3. Migrate SolarEdge Flow History (Load)
        migrate_csv_to_table(
            "solaredge_flow_history.csv",
            "CREATE TABLE IF NOT EXISTS solaredge_flow_history (timestamp TEXT PRIMARY KEY, pv_power_kw REAL NOT NULL, load_power_kw REAL NOT NULL, grid_import_kw REAL NOT NULL, grid_export_kw REAL NOT NULL)",
            "INSERT OR IGNORE INTO solaredge_flow_history (timestamp, pv_power_kw, load_power_kw, grid_import_kw, grid_export_kw) VALUES (?, ?, ?, ?, ?)",
            "CREATE INDEX IF NOT EXISTS idx_se_flow_timestamp ON solaredge_flow_history(timestamp)",
            [1, 2, 3, 4]
        )

        # 4. Migrate Chillicon History
        migrate_csv_to_table(
            "chilicon_history.csv",
            "CREATE TABLE IF NOT EXISTS chilicon_history (timestamp TEXT PRIMARY KEY, power_kw REAL NOT NULL, lifetime_wh REAL NOT NULL)",
            "INSERT OR IGNORE INTO chilicon_history (timestamp, power_kw, lifetime_wh) VALUES (?, ?, ?)",
            "CREATE INDEX IF NOT EXISTS idx_ch_timestamp ON chilicon_history(timestamp)",
            [1, 2]
        )

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Warning] Failed to migrate CSVs to local database: {e}")

    return dest_db


def load_telemetry_table(sync_dir: str, window_hours: int = 48) -> str:
    """Loads and aggregates local microgrid telemetry logs into a markdown table.

    Args:
        sync_dir: Path to the local databases and CSV logs directory.
        window_hours: Number of hours in the past to load.

    Returns:
        A formatted markdown table representing the hourly data blocks.
    """
    db_path: str = build_local_database(sync_dir)

    now_dt: datetime.datetime = datetime.datetime.now()
    start_dt: datetime.datetime = now_dt - datetime.timedelta(hours=window_hours)
    start_hour_dt: datetime.datetime = start_dt.replace(minute=0, second=0, microsecond=0)

    # Generate the hourly keys
    target_hours: List[datetime.datetime] = [
        start_hour_dt + datetime.timedelta(hours=i) for i in range(window_hours + 1)
    ]
    hour_keys: List[str] = [dt.strftime("%Y-%m-%d %H:00") for dt in target_hours]

    # Initialize the data map
    data: Dict[str, Dict[str, float]] = {
        hk: {
            "grid": 0.0,
            "se": 0.0,
            "ch": 0.0,
            "bat_power": 0.0,
            "bat_soc": 0.0,
            "load": 0.0
        }
        for hk in hour_keys
    }

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cutoff_str: str = start_hour_dt.isoformat()

        # 1. Fetch grid average power per hour
        cursor.execute("""
            SELECT strftime('%Y-%m-%d %H:00', timestamp) as hr, AVG(kw) 
            FROM grid_history 
            WHERE timestamp >= ? 
            GROUP BY hr
        """, (cutoff_str,))
        for row in cursor.fetchall():
            if row[0] in data:
                data[row[0]]["grid"] = float(row[1])

        # 2. Fetch SolarEdge PV average power per hour
        cursor.execute("""
            SELECT strftime('%Y-%m-%d %H:00', timestamp) as hr, AVG(pv_kw) 
            FROM solaredge_history 
            WHERE timestamp >= ? 
            GROUP BY hr
        """, (cutoff_str,))
        for row in cursor.fetchall():
            if row[0] in data:
                data[row[0]]["se"] = float(row[1])

        # 3. Fetch Chillicon PV average power per hour
        cursor.execute("""
            SELECT strftime('%Y-%m-%d %H:00', timestamp) as hr, AVG(power_kw) 
            FROM chilicon_history 
            WHERE timestamp >= ? 
            GROUP BY hr
        """, (cutoff_str,))
        for row in cursor.fetchall():
            if row[0] in data:
                data[row[0]]["ch"] = float(row[1])

        # 4. Fetch Battery average power and SoC per hour
        cursor.execute("""
            SELECT strftime('%Y-%m-%d %H:00', timestamp) as hr, AVG(battery_kw), AVG(soc) 
            FROM solaredge_battery_history 
            WHERE timestamp >= ? 
            GROUP BY hr
        """, (cutoff_str,))
        for row in cursor.fetchall():
            if row[0] in data:
                data[row[0]]["bat_power"] = float(row[1])
                data[row[0]]["bat_soc"] = float(row[2])

        # 5. Fetch Load flow average power per hour
        cursor.execute("""
            SELECT strftime('%Y-%m-%d %H:00', timestamp) as hr, AVG(load_power_kw) 
            FROM solaredge_flow_history 
            WHERE timestamp >= ? 
            GROUP BY hr
        """, (cutoff_str,))
        for row in cursor.fetchall():
            if row[0] in data:
                data[row[0]]["load"] = float(row[1])

        conn.close()
    except Exception as e:
        print(f"[Warning] Failed to query local SQLite tables: {e}")

    # Render markdown table rows
    rows_markdown: List[str] = [
        "| Hour | Net Grid (kW) | SolarEdge PV (kW) | Chilicon PV (kW) | Battery SoC | Battery Power (kW) | House Load (kW) |",
        "|---|---|---|---|---|---|---|",
    ]

    for hk in hour_keys:
        avg_grid = data[hk]["grid"]
        avg_se = data[hk]["se"]
        avg_ch = data[hk]["ch"]
        avg_soc = data[hk]["bat_soc"]
        avg_bat_pow = data[hk]["bat_power"]
        avg_load = data[hk]["load"]

        # Fallback to physical load balance if load records are completely missing
        if avg_load == 0.0 and (avg_grid != 0.0 or avg_se != 0.0 or avg_ch != 0.0):
            avg_solar = avg_se + avg_ch
            avg_load = max(0.0, avg_grid + avg_solar + avg_bat_pow)

        rows_markdown.append(
            f"| {hk} | {avg_grid:.3f} | {avg_se:.3f} | {avg_ch:.3f} | {avg_soc:.1f}% | {avg_bat_pow:.3f} | {avg_load:.3f} |"
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


def sync_annotations_to_remote(sync_dir: str) -> None:
    """Rsyncs local user_annotations.json to the remote Jetson Edge AI server.

    Args:
        sync_dir: Path to the local sync directory containing user_annotations.json.

    Returns:
        None.
    """
    path: str = os.path.join(sync_dir, "user_annotations.json")
    if not os.path.exists(path):
        return

    # Configuration for ssh / rsync
    jetson_host: str = os.getenv("JETSON_HOST", "nvjetson")
    jetson_user: str = os.getenv("JETSON_SSH_USER") or os.getenv("JETSON_USER") or "steven"
    target_path: str = "/home/grid_backup/backups/user_annotations.json"

    print(f"[Sync] Pushing user_annotations.json to Jetson ({jetson_user}@{jetson_host})...")

    import subprocess
    try:
        # First try: rsync directly to backups path (if user has write privileges or group write)
        cmd: List[str] = ["rsync", "-avz", path, f"{jetson_user}@{jetson_host}:{target_path}"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            print("[Sync] Direct annotations sync succeeded.")
            return

        # Second try: copy to home directory and then move via sudo
        fallback_cmd: List[str] = ["rsync", "-avz", path, f"{jetson_user}@{jetson_host}:~/user_annotations.json"]
        res_fb = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res_fb.returncode == 0:
            print("[Sync] Copied annotations to user home directory on Jetson. Moving to backups...")
            mv_cmd: List[str] = [
                "ssh", f"{jetson_user}@{jetson_host}",
                f"sudo cp ~/user_annotations.json {target_path} && sudo chown grid_backup:grid_backup {target_path}"
            ]
            res_mv = subprocess.run(mv_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res_mv.returncode == 0:
                print("[Sync] Sudo move and ownership update succeeded.")
            else:
                print(f"[Sync Warning] Failed to move annotations to backups via sudo: {res_mv.stderr.strip()}")
        else:
            print(f"[Sync Warning] Failed to push annotations to home: {res_fb.stderr.strip()}")
    except Exception as e:
        print(f"[Sync Error] Subprocess error during annotations sync: {e}")



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


def execute_sql(db_path: str, sql: str) -> str:
    """Executes a SQLite query against local_repl.db with backups/analysis_history.db attached.

    Args:
        db_path: The path to local_repl.db.
        sql: The SQL query string.

    Returns:
        A formatted string containing the query results or error message.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        backups_db_path = os.path.join(script_dir, "backups/analysis_history.db")
        if os.path.exists(backups_db_path):
            conn.execute(f"ATTACH DATABASE '{backups_db_path}' AS backups_db")
            
        cursor = conn.cursor()
        cursor.execute(sql)
        
        # Get column names
        if cursor.description:
            cols = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            if not rows:
                return "Query executed successfully. No rows returned."
            
            # Format as a clean markdown table
            res = [f"| {' | '.join(cols)} |", f"| {' | '.join(['---'] * len(cols))} |"]
            for row in rows:
                row_str = []
                for val in row:
                    if val is None:
                        row_str.append("NULL")
                    elif isinstance(val, float):
                        row_str.append(f"{val:.3f}")
                    else:
                        row_str.append(str(val))
                res.append(f"| {' | '.join(row_str)} |")
            return "\n".join(res)
        else:
            conn.commit()
            return f"Query executed successfully. Rows affected: {cursor.rowcount}"
    except Exception as e:
        return f"Error executing SQL: {e}"
    finally:
        if conn:
            conn.close()


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
                sync_annotations_to_remote(SYNC_DIR)
                
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
            annotations_str = f"No existing annotations found in this {TELEMETRY_WINDOW_HOURS}-hour window."

        # Format system prompt context dynamically by loading from file
        prompt_template: str = load_system_prompt("repl_system_prompt.txt")
        try:
            system_context = prompt_template.format(
                telemetry_window_hours=TELEMETRY_WINDOW_HOURS,
                telemetry_table=telemetry_table,
                annotations_str=annotations_str,
                current_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        except KeyError as ke:
            print(f"[Warning] Format key missing in prompt file: {ke}")
            # Fallback if bracket parsing fails (e.g. from raw SQL queries in prompt)
            system_context = prompt_template


        # Build structured message list for Ollama's chat API
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_context}
        ]
        
        # Add conversation history
        messages.extend(chat_history)
        
        # Add current user prompt
        messages.append({"role": "user", "content": prompt_text})

        # Run completion tool-execution loop
        active_messages = list(messages)
        tool_executed = False
        final_response_text = ""
        final_response_thinking = ""
        
        # Maximum 5 iterations to allow multiple tool calls, but prevent infinite loops
        for iteration in range(5):
            payload = {
                "model": OLLAMA_MODEL,
                "messages": active_messages,
                "stream": False,
                "options": {
                    "temperature": DEFAULT_TEMPERATURE,
                    "num_predict": DEFAULT_MAX_NEW_TOKENS,
                    "num_ctx": 16384
                }
            }

            if not tool_executed:
                print("Waiting for response...")
            else:
                print("Waiting for agent to process query results...")
            
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
                    
                    if response_thinking and not tool_executed:
                        print("\n[Thinking Process]")
                        print(response_thinking)
                        print("-" * 50)
                    
                    # Look for tool call tags
                    tool_call_match = re.search(r'<tool_call>(.*?)</tool_call>', response_text, re.DOTALL)
                    if tool_call_match:
                        tool_json_str = tool_call_match.group(1).strip()
                        print(f"\n[Executing Tool Call]: {tool_json_str}")
                        sql_query = ""
                        try:
                            tool_data = json.loads(tool_json_str)
                            sql_query = tool_data.get("sql", "")
                        except Exception:
                            # Fallback: extract SELECT query directly if not well-formed JSON
                            sql_match = re.search(r'(SELECT\s+.*)', tool_json_str, re.IGNORECASE | re.DOTALL)
                            if sql_match:
                                sql_query = sql_match.group(1).strip()
                        
                        if sql_query:
                            print(f"[Executing SQL]: {sql_query}")
                            db_path = os.path.join(SYNC_DIR, "local_repl.db")
                            query_res = execute_sql(db_path, sql_query)
                            print(f"[Results]:\n{query_res}\n")
                            
                            # Append the assistant's output with tool call and the tool's result to active_messages
                            active_messages.append({"role": "assistant", "content": response_text})
                            active_messages.append({"role": "user", "content": f"TOOL RESULT:\n{query_res}"})
                            tool_executed = True
                            continue  # Loop back and send active_messages to the model
                        else:
                            print("[Error] Failed to extract valid SQL from tool call.")
                    
                    # If we get here, no tool call was executed. This is the final response.
                    final_response_text = response_text
                    final_response_thinking = response_thinking
                    break
            except urllib.error.HTTPError as e:
                try:
                    error_body = e.read().decode("utf-8")
                    print(f"\n[Error] Server returned HTTP {e.code}: {error_body}\n")
                except Exception:
                    print(f"\n[Error] Server returned HTTP {e.code}: {e.reason}\n")
                break
            except urllib.error.URLError as e:
                print(f"\n[Error] Failed to connect to server at {SERVER_URL}: {e.reason}\n")
                break
            except Exception as e:
                print(f"\n[Error] An unexpected error occurred: {e}\n")
                break
        
        # If we got a final response, display and log it
        if final_response_text or final_response_thinking:
            print("\nResponse:")
            if final_response_text:
                print(final_response_text)
            else:
                print("<Empty response content>")
            print()
            
            # Update history using role-based keys matching Ollama chat API
            chat_history.append({"role": "user", "content": prompt_text})
            stored_response = final_response_text if final_response_text else (f"Thinking: {final_response_thinking}" if final_response_thinking else "")
            chat_history.append({"role": "assistant", "content": stored_response})
            if len(chat_history) > 10:  # Keep last 5 rounds of conversation
                chat_history = chat_history[-10:]
            
            # Log the conversation history to persistent storage for later analysis
            log_chat_message(SYNC_DIR, "user", prompt_text)
            log_chat_message(SYNC_DIR, "assistant", stored_response)

        previous_user_input = user_input


if __name__ == "__main__":
    run_repl()

"""Mock database and CSV telemetry log manager for local gRPC emulation.

Provides helpers to generate SQLite databases, copy active repository CSV logs
to a sandbox path, and write mock records for test validation.
"""

import csv
import datetime
import os
import shutil
import sqlite3
from typing import List, Optional, Tuple


def init_mock_databases(backup_path: str) -> None:
    """Initializes mock grid_history and analysis_history SQLite databases.

    Args:
        backup_path: Directory path where the database files should be created.

    Raises:
        sqlite3.Error: If database initialization fails.
    """
    os.makedirs(backup_path, exist_ok=True)

    # 1. Initialize grid_history.db
    grid_db: str = os.path.join(backup_path, "grid_history.db")
    grid_conn = sqlite3.connect(grid_db)
    grid_cursor = grid_conn.cursor()
    grid_cursor.execute("""
        CREATE TABLE IF NOT EXISTS grid_history (
            timestamp TEXT PRIMARY KEY,
            kw REAL NOT NULL
        )
    """)
    grid_cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_grid_timestamp ON grid_history(timestamp)"
    )
    grid_conn.commit()
    grid_conn.close()

    # 2. Initialize analysis_history.db
    analysis_db: str = os.path.join(backup_path, "analysis_history.db")
    analysis_conn = sqlite3.connect(analysis_db)
    analysis_cursor = analysis_conn.cursor()
    analysis_cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_history (
            timestamp TEXT PRIMARY KEY,
            baseline_timestamp TEXT NOT NULL,
            baseline_text TEXT,
            summary_text TEXT,
            dft_explanation TEXT,
            delta_import REAL NOT NULL,
            delta_export REAL NOT NULL,
            delta_peak REAL NOT NULL,
            delta_solar REAL NOT NULL,
            delta_se_solar REAL NOT NULL,
            delta_ch_solar REAL NOT NULL,
            delta_bat_charge REAL NOT NULL,
            delta_bat_discharge REAL NOT NULL,
            delta_se_load REAL NOT NULL,
            se_load_min REAL NOT NULL,
            se_load_max REAL NOT NULL,
            se_load_avg REAL NOT NULL,
            expected_temp_max REAL,
            expected_cloud_cover REAL,
            spectral_metrics_json TEXT,
            escalation_status INTEGER DEFAULT 0,
            escalation_timestamp TEXT
        )
    """)
    analysis_cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_escalation ON analysis_history(escalation_status)"
    )
    analysis_conn.commit()
    analysis_conn.close()


def populate_mock_csvs(backup_path: str, src_path: str) -> None:
    """Copies active telemetry logs from workspace or writes fallback mock data.

    Args:
        backup_path: The sandbox output directory.
        src_path: The source workspace directory containing current files.
    """
    os.makedirs(backup_path, exist_ok=True)
    csv_filenames: List[str] = [
        "solaredge_history.csv",
        "solaredge_battery_history.csv",
        "solaredge_flow_history.csv",
        "chilicon_history.csv",
    ]

    for fname in csv_filenames:
        src_file: str = os.path.join(src_path, fname)
        dest_file: str = os.path.join(backup_path, fname)

        if os.path.exists(src_file):
            # Copy active development files to sandbox for testing with actual logs
            shutil.copy2(src_file, dest_file)
        else:
            # Fallback mock writer if running in an environment without active logs
            with open(dest_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                now_iso: str = datetime.datetime.now().isoformat()
                if fname == "solaredge_history.csv":
                    writer.writerow([now_iso, "1.500"])
                elif fname == "solaredge_battery_history.csv":
                    writer.writerow([now_iso, "0.500", "80.0"])
                elif fname == "solaredge_flow_history.csv":
                    writer.writerow([now_iso, "1.500", "2.000", "0.500", "0.000"])
                elif fname == "chilicon_history.csv":
                    writer.writerow([now_iso, "0.800", "21700.0"])


def insert_mock_grid_reading(db_path: str, timestamp: str, kw: float) -> None:
    """Inserts a single grid telemetry reading into the mock database.

    Args:
        db_path: Path to the SQLite grid database.
        timestamp: ISO 8601 format timestamp string of the reading.
        kw: Electrical demand in kilowatts.

    Raises:
        sqlite3.Error: If insertion query fails.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO grid_history (timestamp, kw) VALUES (?, ?)",
        (timestamp, kw),
    )
    conn.commit()
    conn.close()


def insert_mock_analysis_record(
    db_path: str,
    timestamp: str,
    baseline_timestamp: str,
    baseline_text: str,
    summary_text: str,
    dft_explanation: str,
    deltas: Tuple[float, float, float, float, float, float, float, float, float],
    load_stats: Tuple[float, float, float],
    weather: Tuple[float, float],
    spectral_metrics_json: str,
    escalation_status: int = 0,
    escalation_timestamp: Optional[str] = None,
) -> None:
    """Inserts a completed local analysis record into the mock database.

    Args:
        db_path: Path to the SQLite analysis database.
        timestamp: Time of generation (ISO string).
        baseline_timestamp: Timestamp of baseline context used.
        baseline_text: Raw baseline summary context used in instructions.
        summary_text: Local LLM generated live delta summary.
        dft_explanation: Local LLM generated DFT explanation.
        deltas: Tuple containing (import, export, peak, solar, se_solar,
          ch_solar, bat_charge, bat_discharge, se_load) in kWh/kW.
        load_stats: Tuple of (load_min, load_max, load_avg) in kW.
        weather: Tuple of (expected_temp_max, expected_cloud_cover).
        spectral_metrics_json: Serialized JSON of all calculated spectral metrics.
        escalation_status: Gating status (0=Normal, 1=Escalated, 2=Pending Retry).
        escalation_timestamp: Time of cloud handover (ISO string).

    Raises:
        sqlite3.Error: If database query execution fails.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO analysis_history (
            timestamp, baseline_timestamp, baseline_text, summary_text, dft_explanation,
            delta_import, delta_export, delta_peak, delta_solar, delta_se_solar,
            delta_ch_solar, delta_bat_charge, delta_bat_discharge, delta_se_load,
            se_load_min, se_load_max, se_load_avg, expected_temp_max, expected_cloud_cover,
            spectral_metrics_json, escalation_status, escalation_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp,
            baseline_timestamp,
            baseline_text,
            summary_text,
            dft_explanation,
            deltas[0],
            deltas[1],
            deltas[2],
            deltas[3],
            deltas[4],
            deltas[5],
            deltas[6],
            deltas[7],
            deltas[8],
            load_stats[0],
            load_stats[1],
            load_stats[2],
            weather[0],
            weather[1],
            spectral_metrics_json,
            escalation_status,
            escalation_timestamp,
        ),
    )
    conn.commit()
    conn.close()

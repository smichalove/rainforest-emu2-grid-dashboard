"""SQLite database management and query utilities for Rainforest grid telemetry.

Provides initialization, safe inserts, history loading, and hourly aggregation functions.
"""

import sqlite3
import os
import logging
import datetime
from typing import List, Tuple, Optional, Dict, Any


def init_db(db_path: str) -> None:
    """Initializes the SQLite database, creating tables and indexes if missing.

    Args:
        db_path: Absolute filesystem path to the SQLite database file.

    Raises:
        sqlite3.Error: If database connection or schema execution fails.
    """
    try:
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Primary key on timestamp prevents duplicate telemetry reads from inserting
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS grid_history (
                timestamp TEXT PRIMARY KEY,
                kw REAL NOT NULL
            )
        """)
        
        # Index on timestamp accelerates historical range queries (DFT, sliding windows)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_grid_timestamp ON grid_history(timestamp)")
        
        conn.commit()
        conn.close()
        logging.info(f"Database initialized successfully at: {db_path}")
    except sqlite3.Error as e:
        logging.error(f"Failed to initialize SQLite database at {db_path}: {e}")
        raise


def insert_reading(db_path: str, timestamp: str, kw: float) -> bool:
    """Inserts a single grid telemetry demand reading into the database.

    Uses INSERT OR IGNORE to handle duplicate serial messages gracefully.

    Args:
        db_path: Absolute filesystem path to the SQLite database file.
        timestamp: ISO format naive timestamp string of the reading.
        kw: Power demand in kilowatts (kW).

    Returns:
        True if insertion succeeded, False otherwise.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO grid_history (timestamp, kw) VALUES (?, ?)",
            (timestamp, kw)
        )
        conn.commit()
        # rowcount will be 1 if inserted, 0 if duplicate/ignored
        success = cursor.rowcount > 0
        conn.close()
        return success
    except sqlite3.Error as e:
        logging.error(f"Failed to insert reading ({timestamp}, {kw}) into database: {e}")
        return False


def query_history(
    db_path: str,
    cutoff_hours: int = 24,
    reference_time: Optional[datetime.datetime] = None
) -> Tuple[List[datetime.datetime], List[float]]:
    """Loads historical measurements from database within the sliding time window.

    Args:
        db_path: Absolute filesystem path to the SQLite database file.
        cutoff_hours: Number of hours in the past to load.
        reference_time: Optional reference datetime to calculate the cutoff from.
            If None, defaults to the current system time.

    Returns:
        A tuple containing:
            - List of datetime objects representing timestamps.
            - List of floats representing power readings in kW.
    """
    timestamps: List[datetime.datetime] = []
    usage: List[float] = []
    
    if not os.path.exists(db_path):
        return timestamps, usage

    # Calculate ISO threshold string relative to the reference time
    ref = reference_time if reference_time is not None else datetime.datetime.now()
    cutoff = ref - datetime.timedelta(hours=cutoff_hours)
    cutoff_str = cutoff.isoformat()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp, kw FROM grid_history WHERE timestamp > ? ORDER BY timestamp ASC",
            (cutoff_str,)
        )
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            try:
                ts = datetime.datetime.fromisoformat(row[0])
                val = float(row[1])
                timestamps.append(ts)
                usage.append(val)
            except Exception as parse_err:
                logging.debug(f"Skipping corrupted database row {row}: {parse_err}")
    except sqlite3.Error as e:
        logging.error(f"Failed to query grid history: {e}")
        
    return timestamps, usage


def query_hourly_aggregates(
    db_path: str, start_time: str, end_time: str
) -> List[Tuple[str, float, float, float, float]]:
    """Queries hourly averages, minimums, maximums, and row counts from SQLite.

    Performs optimized database-level aggregation to get hourly statistics.

    Args:
        db_path: Absolute filesystem path to the SQLite database file.
        start_time: ISO timestamp string representing the start of the evaluation window.
        end_time: ISO timestamp string representing the end of the evaluation window.

    Returns:
        A list of tuples, where each tuple is:
            (hour_str, avg_kw, min_kw, max_kw, median_kw)
            Note: median is approximated by the average for simple SQL queries, or computed
            exactly on the subset. Here we return: (hour_str, avg_kw, min_kw, max_kw, median_kw)
            where median is represented by the average value to avoid heavy SQL operations.
    """
    results: List[Tuple[str, float, float, float, float]] = []
    if not os.path.exists(db_path):
        return results

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # SQL aggregation groups 15-second records into hourly buckets ("YYYY-MM-DD HH:00")
        cursor.execute("""
            SELECT 
                strftime('%Y-%m-%d %H:00', timestamp) as hour_key,
                AVG(kw) as avg_val,
                MIN(kw) as min_val,
                MAX(kw) as max_val
            FROM grid_history
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY hour_key
            ORDER BY hour_key ASC
        """, (start_time, end_time))
        
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            hour_str = row[0]
            avg_val = float(row[1])
            min_val = float(row[2])
            max_val = float(row[3])
            # For simplicity, map median to average value in SQL aggregates
            median_val = avg_val
            results.append((hour_str, avg_val, min_val, max_val, median_val))
    except sqlite3.Error as e:
        logging.error(f"Failed to query hourly aggregates: {e}")
        
    return results


def migrate_csv(db_path: str, csv_path: str) -> int:
    """Migrates existing records from flat CSV file into the SQLite database.

    Args:
        db_path: Absolute filesystem path to the SQLite database file.
        csv_path: Absolute path to the CSV file to migrate.

    Returns:
        The total number of records successfully migrated.
    """
    if not os.path.exists(csv_path):
        logging.warning(f"Migration: Source CSV file {csv_path} does not exist. Skipping.")
        return 0

    init_db(db_path)
    
    # Read and clean CSV rows safely
    from .io import read_clean_csv
    rows = read_clean_csv(csv_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    migrated_count = 0
    batch = []
    
    for row in rows:
        if len(row) == 2:
            ts = row[0].strip()
            val_str = row[1].strip()
            try:
                # Basic validation
                datetime.datetime.fromisoformat(ts)
                val = float(val_str)
                batch.append((ts, val))
            except ValueError:
                continue
                
            if len(batch) >= 5000:
                cursor.executemany("INSERT OR IGNORE INTO grid_history (timestamp, kw) VALUES (?, ?)", batch)
                migrated_count += cursor.rowcount
                batch = []
                
    if batch:
        cursor.executemany("INSERT OR IGNORE INTO grid_history (timestamp, kw) VALUES (?, ?)", batch)
        migrated_count += cursor.rowcount
        
    conn.commit()
    conn.close()
    
    logging.info(f"Successfully migrated {migrated_count} records from {csv_path} to {db_path}")
    return migrated_count


def insert_analysis_history(db_path: str, record: Dict[str, Any]) -> bool:
    """Inserts a completed AI analysis record into the analysis_history database.

    Args:
        db_path: The absolute filesystem path to the analysis SQLite database file.
        record: A dictionary containing all the database column key-values.

    Returns:
        A boolean indicating True if insertion was successful, False otherwise.

    Raises:
        sqlite3.Error: If the SQL query fails (logged and caught internally).
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # We use INSERT OR REPLACE to update if the same timestamp is evaluated again
        cursor.execute("""
            INSERT OR REPLACE INTO analysis_history (
                timestamp, baseline_timestamp, baseline_text, summary_text, dft_explanation,
                delta_import, delta_export, delta_peak, delta_solar, delta_se_solar,
                delta_ch_solar, delta_bat_charge, delta_bat_discharge, delta_se_load,
                se_load_min, se_load_max, se_load_avg, expected_temp_max, expected_cloud_cover,
                spectral_metrics_json, escalation_status, escalation_timestamp
            ) VALUES (
                :timestamp, :baseline_timestamp, :baseline_text, :summary_text, :dft_explanation,
                :delta_import, :delta_export, :delta_peak, :delta_solar, :delta_se_solar,
                :delta_ch_solar, :delta_bat_charge, :delta_bat_discharge, :delta_se_load,
                :se_load_min, :se_load_max, :se_load_avg, :expected_temp_max, :expected_cloud_cover,
                :spectral_metrics_json, :escalation_status, :escalation_timestamp
            )
        """, record)
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success
    except sqlite3.Error as e:
        logging.error(f"Failed to insert analysis history record: {e}")
        return False


def query_solaredge_history(
    db_path: str,
    cutoff_hours: int = 24,
    reference_time: Optional[datetime.datetime] = None
) -> Tuple[List[datetime.datetime], List[float], List[datetime.datetime], List[float], List[float]]:
    """Queries SolarEdge PV and battery history tables from SQLite.

    Args:
        db_path: The absolute path to the SQLite database.
        cutoff_hours: Number of hours in the past to load.
        reference_time: Optional reference datetime.

    Returns:
        Tuple: (pv_timestamps, pv_power, battery_timestamps, battery_power, battery_soc)
    """
    pv_ts: List[datetime.datetime] = []
    pv_power: List[float] = []
    bat_ts: List[datetime.datetime] = []
    bat_power: List[float] = []
    bat_soc: List[float] = []

    if not os.path.exists(db_path):
        return pv_ts, pv_power, bat_ts, bat_power, bat_soc

    ref = reference_time if reference_time is not None else datetime.datetime.now()
    cutoff = ref - datetime.timedelta(hours=cutoff_hours)
    cutoff_str = cutoff.isoformat()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Query SolarEdge PV power
        cursor.execute(
            "SELECT timestamp, pv_kw FROM solaredge_history WHERE timestamp > ? ORDER BY timestamp ASC",
            (cutoff_str,)
        )
        for row in cursor.fetchall():
            try:
                pv_ts.append(datetime.datetime.fromisoformat(row[0]))
                pv_power.append(float(row[1]))
            except Exception as e:
                logging.debug(f"Error parsing solaredge_history db row: {row} - {e}")

        # Query SolarEdge Battery power & SoC
        cursor.execute(
            "SELECT timestamp, battery_kw, soc FROM solaredge_battery_history WHERE timestamp > ? ORDER BY timestamp ASC",
            (cutoff_str,)
        )
        for row in cursor.fetchall():
            try:
                bat_ts.append(datetime.datetime.fromisoformat(row[0]))
                bat_power.append(float(row[1]))
                bat_soc.append(float(row[2]))
            except Exception as e:
                logging.debug(f"Error parsing solaredge_battery_history db row: {row} - {e}")

        conn.close()
    except sqlite3.Error as e:
        logging.error(f"Failed to query SolarEdge database history: {e}")

    return pv_ts, pv_power, bat_ts, bat_power, bat_soc


def query_solaredge_flow_history(
    db_path: str,
    cutoff_hours: int = 24,
    reference_time: Optional[datetime.datetime] = None
) -> Tuple[List[datetime.datetime], List[float]]:
    """Queries SolarEdge load flow history (specifically load_power_kw) from SQLite.

    Args:
        db_path: The absolute path to the SQLite database.
        cutoff_hours: Number of hours in the past to load.
        reference_time: Optional reference datetime.

    Returns:
        Tuple: (timestamps, load_power_kw)
    """
    load_ts: List[datetime.datetime] = []
    load_power: List[float] = []

    if not os.path.exists(db_path):
        return load_ts, load_power

    ref = reference_time if reference_time is not None else datetime.datetime.now()
    cutoff = ref - datetime.timedelta(hours=cutoff_hours)
    cutoff_str = cutoff.isoformat()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp, load_power_kw FROM solaredge_flow_history WHERE timestamp > ? ORDER BY timestamp ASC",
            (cutoff_str,)
        )
        for row in cursor.fetchall():
            try:
                load_ts.append(datetime.datetime.fromisoformat(row[0]))
                load_power.append(float(row[1]))
            except Exception as e:
                logging.debug(f"Error parsing solaredge_flow_history db row: {row} - {e}")
        conn.close()
    except sqlite3.Error as e:
        logging.error(f"Failed to query SolarEdge flow database history: {e}")

    return load_ts, load_power


def query_chilicon_history(
    db_path: str,
    cutoff_hours: int = 24,
    reference_time: Optional[datetime.datetime] = None
) -> Tuple[List[datetime.datetime], List[float], List[float]]:
    """Queries Chillicon PV history (power_kw and lifetime_wh) from SQLite.

    Args:
        db_path: The absolute path to the SQLite database.
        cutoff_hours: Number of hours in the past to load.
        reference_time: Optional reference datetime.

    Returns:
        Tuple: (timestamps, power_kw, lifetime_wh)
    """
    ch_ts: List[datetime.datetime] = []
    ch_power: List[float] = []
    ch_energy: List[float] = []

    if not os.path.exists(db_path):
        return ch_ts, ch_power, ch_energy

    ref = reference_time if reference_time is not None else datetime.datetime.now()
    cutoff = ref - datetime.timedelta(hours=cutoff_hours)
    cutoff_str = cutoff.isoformat()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp, power_kw, lifetime_wh FROM chilicon_history WHERE timestamp > ? ORDER BY timestamp ASC",
            (cutoff_str,)
        )
        for row in cursor.fetchall():
            try:
                ch_ts.append(datetime.datetime.fromisoformat(row[0]))
                ch_power.append(float(row[1]))
                ch_energy.append(float(row[2]))
            except Exception as e:
                logging.debug(f"Error parsing chilicon_history db row: {row} - {e}")
        conn.close()
    except sqlite3.Error as e:
        logging.error(f"Failed to query Chillicon database history: {e}")

    return ch_ts, ch_power, ch_energy


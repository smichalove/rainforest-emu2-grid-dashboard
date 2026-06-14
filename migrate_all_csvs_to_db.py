"""Utility script to migrate historical CSV telemetry data to SQLite tables.

Enables ad-hoc SQL querying and joins in DBeaver on the local development machine
by importing SolarEdge and Chillicon telemetry logs from CSV files into
separate tables inside the grid_history SQLite database.
"""

import csv
import logging
import os
import sqlite3
from typing import List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Resolve workspace root dynamically as the directory containing this script.
WORKSPACE_DIR: str = os.path.dirname(os.path.abspath(__file__))
# In the staging structure, databases are initialized inside the backups/ folder.
DB_PATH: str = os.path.join(WORKSPACE_DIR, "backups", "grid_history.db")


def migrate_solaredge_history(db_conn: sqlite3.Connection, csv_path: str) -> int:
    """Migrates solaredge_history.csv to solaredge_history table.

    Args:
        db_conn: An active sqlite3.Connection object.
        csv_path: Path to the SolarEdge PV history CSV file.

    Returns:
        The number of successfully migrated records.
    """
    cursor = db_conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solaredge_history (
            timestamp TEXT PRIMARY KEY,
            pv_kw REAL NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_se_timestamp ON solaredge_history(timestamp)")
    
    rows: List[Tuple[str, float]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                try:
                    ts = row[0].strip()
                    pv = float(row[1])
                    rows.append((ts, pv))
                except ValueError:
                    continue
                    
    if rows:
        cursor.executemany("INSERT OR IGNORE INTO solaredge_history (timestamp, pv_kw) VALUES (?, ?)", rows)
        inserted = cursor.rowcount
        db_conn.commit()
        return inserted
    return 0


def migrate_solaredge_battery_history(db_conn: sqlite3.Connection, csv_path: str) -> int:
    """Migrates solaredge_battery_history.csv to solaredge_battery_history table.

    Args:
        db_conn: An active sqlite3.Connection object.
        csv_path: Path to the SolarEdge battery history CSV file.

    Returns:
        The number of successfully migrated records.
    """
    cursor = db_conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solaredge_battery_history (
            timestamp TEXT PRIMARY KEY,
            battery_kw REAL NOT NULL,
            soc REAL NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_se_bat_timestamp ON solaredge_battery_history(timestamp)")
    
    rows: List[Tuple[str, float, float]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 3:
                try:
                    ts = row[0].strip()
                    pwr = float(row[1])
                    soc = float(row[2])
                    rows.append((ts, pwr, soc))
                except ValueError:
                    continue
                    
    if rows:
        cursor.executemany("INSERT OR IGNORE INTO solaredge_battery_history (timestamp, battery_kw, soc) VALUES (?, ?, ?)", rows)
        inserted = cursor.rowcount
        db_conn.commit()
        return inserted
    return 0


def migrate_solaredge_flow_history(db_conn: sqlite3.Connection, csv_path: str) -> int:
    """Migrates solaredge_flow_history.csv to solaredge_flow_history table.

    Args:
        db_conn: An active sqlite3.Connection object.
        csv_path: Path to the SolarEdge power flow connection history CSV file.

    Returns:
        The number of successfully migrated records.
    """
    cursor = db_conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solaredge_flow_history (
            timestamp TEXT PRIMARY KEY,
            pv_power_kw REAL NOT NULL,
            load_power_kw REAL NOT NULL,
            grid_import_kw REAL NOT NULL,
            grid_export_kw REAL NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_se_flow_timestamp ON solaredge_flow_history(timestamp)")
    
    rows: List[Tuple[str, float, float, float, float]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 5:
                try:
                    ts = row[0].strip()
                    pv = float(row[1])
                    ld = float(row[2])
                    imp = float(row[3])
                    exp = float(row[4])
                    rows.append((ts, pv, ld, imp, exp))
                except ValueError:
                    continue
                    
    if rows:
        cursor.executemany("""
            INSERT OR IGNORE INTO solaredge_flow_history (
                timestamp, pv_power_kw, load_power_kw, grid_import_kw, grid_export_kw
            ) VALUES (?, ?, ?, ?, ?)
        """, rows)
        inserted = cursor.rowcount
        db_conn.commit()
        return inserted
    return 0


def migrate_chilicon_history(db_conn: sqlite3.Connection, csv_path: str) -> int:
    """Migrates chilicon_history.csv to chilicon_history table.

    Args:
        db_conn: An active sqlite3.Connection object.
        csv_path: Path to the Chillicon micro-inverter history CSV file.

    Returns:
        The number of successfully migrated records.
    """
    cursor = db_conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chilicon_history (
            timestamp TEXT PRIMARY KEY,
            power_kw REAL NOT NULL,
            lifetime_wh REAL NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ch_timestamp ON chilicon_history(timestamp)")
    
    rows: List[Tuple[str, float, float]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 3:
                try:
                    ts = row[0].strip()
                    pwr = float(row[1])
                    life = float(row[2])
                    rows.append((ts, pwr, life))
                except ValueError:
                    continue
                    
    if rows:
        cursor.executemany("INSERT OR IGNORE INTO chilicon_history (timestamp, power_kw, lifetime_wh) VALUES (?, ?, ?)", rows)
        inserted = cursor.rowcount
        db_conn.commit()
        return inserted
    return 0


def main() -> None:
    """Entry point for executing telemetry CSV migration."""
    logging.info("Starting local telemetry CSV database migration...")
    
    if not os.path.exists(DB_PATH):
        logging.error("Database file not found at: %s", DB_PATH)
        return
        
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # 1. SolarEdge PV
        se_path = os.path.join(WORKSPACE_DIR, "solaredge_history.csv")
        if os.path.exists(se_path):
            count = migrate_solaredge_history(conn, se_path)
            logging.info("Migrated %d records into solaredge_history", count)
        else:
            logging.warning("SolarEdge history CSV not found at: %s", se_path)

        # 2. SolarEdge Battery
        se_bat_path = os.path.join(WORKSPACE_DIR, "solaredge_battery_history.csv")
        if os.path.exists(se_bat_path):
            count = migrate_solaredge_battery_history(conn, se_bat_path)
            logging.info("Migrated %d records into solaredge_battery_history", count)
        else:
            logging.warning("SolarEdge battery history CSV not found at: %s", se_bat_path)

        # 3. SolarEdge Flow
        se_flow_path = os.path.join(WORKSPACE_DIR, "solaredge_flow_history.csv")
        if os.path.exists(se_flow_path):
            count = migrate_solaredge_flow_history(conn, se_flow_path)
            logging.info("Migrated %d records into solaredge_flow_history", count)
        else:
            logging.warning("SolarEdge flow history CSV not found at: %s", se_flow_path)

        # 4. Chillicon PV
        ch_path = os.path.join(WORKSPACE_DIR, "chilicon_history.csv")
        if os.path.exists(ch_path):
            count = migrate_chilicon_history(conn, ch_path)
            logging.info("Migrated %d records into chilicon_history", count)
        else:
            logging.warning("Chillicon history CSV not found at: %s", ch_path)

        conn.close()
        logging.info("Migration complete!")
    except sqlite3.Error as e:
        logging.error("SQLite error encountered during migration: %s", e)


if __name__ == "__main__":
    main()

"""Script to migrate telemetry data and populate SQLite database tables locally.

Initializes grid_history and analysis_history databases in the backups directory,
copies or migrates grid telemetry logs, and verifies database integrity.
"""

import os
import shutil
import sqlite3
import logging
from typing import Optional, Tuple

# Global configuration variables
DEFAULT_BACKUP_DIR: str = "backups"
GRID_DB_NAME: str = "grid_history.db"
ANALYSIS_DB_NAME: str = "analysis_history.db"
GRID_CSV_NAME: str = "grid_history.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def init_analysis_db(db_path: str) -> None:
    """Initializes the analysis history database schema.

    Args:
        db_path: The filesystem path to the analysis database.

    Raises:
        sqlite3.Error: If the SQLite connection or table creation fails.
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create analysis_history table
        cursor.execute("""
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
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_analysis_escalation ON analysis_history(escalation_status)"
        )
        conn.commit()
        conn.close()
        logging.info(f"Analysis database initialized at: {db_path}")
    except sqlite3.Error as e:
        logging.error(f"Failed to initialize analysis database at {db_path}: {e}")
        raise


def migrate_telemetry(workspace_dir: str) -> None:
    """Performs the local data migration to populate the databases.

    Args:
        workspace_dir: The root directory of the repository workspace.
    """
    backup_path: str = os.path.join(workspace_dir, DEFAULT_BACKUP_DIR)
    os.makedirs(backup_path, exist_ok=True)

    dest_grid_db: str = os.path.join(backup_path, GRID_DB_NAME)
    dest_analysis_db: str = os.path.join(backup_path, ANALYSIS_DB_NAME)

    # 1. Initialize analysis_history.db
    init_analysis_db(dest_analysis_db)

    # 2. Populate grid_history.db
    # First, check if the pre-existing root grid_history.db is available.
    # Copying is faster and preserves the full history if present.
    src_grid_db: str = os.path.join(workspace_dir, GRID_DB_NAME)
    if os.path.exists(src_grid_db) and not os.path.exists(dest_grid_db):
        logging.info(f"Found existing root grid database at {src_grid_db}. Copying to {dest_grid_db}...")
        shutil.copy2(src_grid_db, dest_grid_db)
        logging.info("Copy complete.")
    elif not os.path.exists(dest_grid_db):
        logging.info(f"No database found. Initializing new grid database at {dest_grid_db}...")
        # We import the db module from dashboard_modules to perform migration
        import sys
        sys.path.insert(0, workspace_dir)
        from dashboard_modules.db import init_db, migrate_csv
        init_db(dest_grid_db)

        csv_path: str = os.path.join(backup_path, GRID_CSV_NAME)
        if not os.path.exists(csv_path):
            csv_path = os.path.join(workspace_dir, GRID_CSV_NAME)

        if os.path.exists(csv_path):
            logging.info(f"Migrating records from {csv_path}...")
            count: int = migrate_csv(dest_grid_db, csv_path)
            logging.info(f"Migration completed. Migrated {count} records.")
        else:
            logging.warning(f"No grid telemetry CSV found at {csv_path}. Database is empty.")
    else:
        logging.info(f"Grid history database already exists at {dest_grid_db}. Skipping initialization.")

    # 3. Verify Database Contents
    if os.path.exists(dest_grid_db):
        try:
            conn = sqlite3.connect(dest_grid_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM grid_history")
            count = cursor.fetchone()[0]
            cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM grid_history")
            min_ts, max_ts = cursor.fetchone()
            conn.close()
            logging.info(f"Verification: {dest_grid_db} contains {count} telemetry records.")
            logging.info(f"Telemetry range: {min_ts} to {max_ts}")
        except sqlite3.Error as e:
            logging.error(f"Failed to verify grid database: {e}")


if __name__ == "__main__":
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    migrate_telemetry(script_dir)

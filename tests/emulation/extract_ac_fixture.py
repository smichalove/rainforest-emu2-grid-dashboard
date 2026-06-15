"""A/C power spike telemetry extractor for local edge emulation.

Queries the db/grid_history.db database for the 1-hour window on June 14, 2026,
and performs ASOF joins to align high-frequency grid demand with lower-frequency
SolarEdge and Chillicon telemetry, saving the results as a JSON fixture.
"""

import datetime
import json
import os
import sqlite3
from typing import Dict, List, Tuple, Union


def get_latest_telemetry_before(
    cursor: sqlite3.Cursor, table: str, columns: str, timestamp: str
) -> Tuple[float, ...]:
    """Retrieves the closest telemetry reading from a table before or at a timestamp.

    Args:
        cursor: The active SQLite cursor.
        table: The name of the table to query.
        columns: Comma-separated column names to select (excluding timestamp).
        timestamp: The reference ISO 8601 timestamp string.

    Returns:
        A tuple of float values corresponding to the requested columns,
        or a tuple of zeroes if no record is found.
    """
    query: str = f"""
        SELECT {columns}
        FROM {table}
        WHERE timestamp <= ?
        ORDER BY timestamp DESC
        LIMIT 1
    """
    cursor.execute(query, (timestamp,))
    row: Union[Tuple[None], Tuple[float, ...]] = cursor.fetchone()
    if row is None:
        # Return zeroes if no data exists before the timestamp
        num_cols: int = len(columns.split(","))
        return tuple(0.0 for _ in range(num_cols))
    return tuple(float(val) for val in row)


def extract_ac_spike() -> None:
    """Extracts the A/C power spike window telemetry and saves it as a JSON fixture.

    Raises:
        sqlite3.Error: If the database operations fail.
    """
    db_path: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "db",
        "grid_history.db",
    )
    output_path: str = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "ac_spike_fixture.json"
    )

    print(f"Reading from database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all grid history records in the target window
    start_ts: str = "2026-06-14T20:00:00"
    end_ts: str = "2026-06-14T21:00:00"

    cursor.execute(
        """
        SELECT timestamp, kw
        FROM grid_history
        WHERE timestamp BETWEEN ? AND ?
        ORDER BY timestamp ASC
        """,
        (start_ts, end_ts),
    )
    grid_rows: List[Tuple[str, float]] = cursor.fetchall()
    print(f"Found {len(grid_rows)} grid_history records.")

    fixture_readings: List[Dict[str, Union[str, float]]] = []

    for ts, kw in grid_rows:
        # ASOF join for SolarEdge history (pv_kw)
        se_pv: Tuple[float] = get_latest_telemetry_before(cursor, "solaredge_history", "pv_kw", ts)
        
        # ASOF join for SolarEdge battery (battery_kw, soc)
        se_bat: Tuple[float, float] = get_latest_telemetry_before(
            cursor, "solaredge_battery_history", "battery_kw, soc", ts
        )
        
        # ASOF join for SolarEdge flow (pv_power_kw, load_power_kw, grid_import_kw, grid_export_kw)
        se_flow: Tuple[float, float, float, float] = get_latest_telemetry_before(
            cursor, "solaredge_flow_history", "pv_power_kw, load_power_kw, grid_import_kw, grid_export_kw", ts
        )
        
        # ASOF join for Chillicon (power_kw, lifetime_wh)
        ch: Tuple[float, float] = get_latest_telemetry_before(
            cursor, "chilicon_history", "power_kw, lifetime_wh", ts
        )

        reading: Dict[str, Union[str, float]] = {
            "timestamp": ts,
            "grid_usage_kw": kw,
            "solaredge_pv_kw": se_pv[0],
            "solaredge_battery_kw": se_bat[0],
            "solaredge_battery_soc": se_bat[1],
            "solaredge_load_kw": se_flow[1],
            "solaredge_import_kw": se_flow[2],
            "solaredge_export_kw": se_flow[3],
            "chilicon_pv_kw": ch[0],
            "chilicon_lifetime_wh": ch[1],
        }
        fixture_readings.append(reading)

    conn.close()

    fixture_data: Dict[str, Union[str, float, List[Dict[str, Union[str, float]]]]] = {
        "slice_id": "ac_spike_20260614_2000",
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "dft_period_hours": 1.0,
        "readings": fixture_readings,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(fixture_data, f, indent=2)
    print(f"Successfully wrote {len(fixture_readings)} aligned records to {output_path}")


if __name__ == "__main__":
    extract_ac_spike()

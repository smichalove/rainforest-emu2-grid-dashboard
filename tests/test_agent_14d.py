"""Unit tests for 14-day ReAct Agent Loop, Seasonality Context, and SQL Table Extraction.

Tests:
1. get_seasonality_context output and sunrise/sunset formatting.
2. get_14day_daily_breakdown_table generation with SQLite analysis_history schema.
3. execute_sql_query safety checks (disallowing mutating statements).
4. get_ollama_endpoints rotation ordering and host filtering.
"""

import datetime
import os
import sqlite3
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dashboard_modules.agent_loop import (
    get_seasonality_context,
    get_14day_daily_breakdown_table,
    get_ollama_endpoints,
    execute_sql_query,
)


def test_get_seasonality_context():
    """Verifies that seasonality context correctly resolves solar cycle and diurnal profiles."""
    context = get_seasonality_context("2026-10-09 14:00:00")
    assert context["month_name"] == "October"
    assert context["season"] == "Autumn / Fall"
    assert context["sunrise"] == "07:18"
    assert context["sunset"] == "18:31"
    assert context["daylight_hours"] == 11.2
    assert "solar_trend" in context
    assert "load_trend" in context
    assert "battery_role" in context


def test_get_seasonality_context_winter_summer():
    """Verifies seasonal transitions across summer and winter months."""
    ctx_dec = get_seasonality_context("2026-12-15 12:00:00")
    assert ctx_dec["season"] == "Winter"
    assert ctx_dec["sunrise"] == "07:54"
    assert ctx_dec["daylight_hours"] == 8.5

    ctx_jun = get_seasonality_context("2026-06-21 12:00:00")
    assert ctx_jun["season"] == "Summer"
    assert ctx_jun["sunrise"] == "05:11"
    assert ctx_jun["daylight_hours"] == 16.0


def test_execute_sql_query_safety(tmp_path):
    """Verifies that execute_sql_query strictly rejects non-SELECT queries."""
    db_file = tmp_path / "safety_test.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE sample (id INT, val TEXT)")
    cur.execute("INSERT INTO sample VALUES (1, 'active')")
    conn.commit()
    conn.close()

    # Valid SELECT
    res = execute_sql_query(str(db_file), "SELECT * FROM sample")
    assert "active" in res

    # Mutating statements rejected
    drop_res = execute_sql_query(str(db_file), "DROP TABLE sample")
    assert "Security violation" in drop_res or "Only SELECT" in drop_res

    update_res = execute_sql_query(str(db_file), "UPDATE sample SET val = 'hacked'")
    assert "Security violation" in update_res or "Only SELECT" in drop_res


def test_get_14day_daily_breakdown_table(tmp_path):
    """Verifies pre-injected 14-day daily matrix formatting from a mock SQLite database."""
    db_file = tmp_path / "test_grid.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE analysis_history (
            timestamp TEXT PRIMARY KEY,
            delta_import REAL,
            delta_export REAL,
            delta_solar REAL,
            delta_bat_charge REAL,
            delta_bat_discharge REAL,
            delta_peak REAL,
            delta_se_load REAL
        )
    """)
    
    # Insert 3 days of telemetry
    records = [
        ("2026-10-07 08:00:00", 1.5, 0.0, 0.5, 0.2, 0.0, 3.2, 1.8),
        ("2026-10-07 13:00:00", 0.0, 2.0, 4.5, 2.5, 0.0, 2.1, 2.0),
        ("2026-10-08 09:00:00", 0.8, 0.5, 2.0, 0.5, 0.0, 2.5, 1.5),
        ("2026-10-08 19:00:00", 2.2, 0.0, 0.0, 0.0, 1.8, 4.0, 2.2), # Flex event candidate
    ]
    cur.executemany("INSERT INTO analysis_history VALUES (?, ?, ?, ?, ?, ?, ?, ?)", records)
    conn.commit()
    conn.close()

    table_text = get_14day_daily_breakdown_table(str(db_file), analysis_db_path=str(db_file))
    assert "| Date" in table_text
    assert "10-07" in table_text
    assert "10-08" in table_text
    # 2026-10-08 had delta_bat_discharge = 1.8 > 0.5, so it triggers ⚡ Flex
    assert "⚡ PSE Flex Event" in table_text


def test_get_ollama_endpoints():
    """Verifies sequential Ollama endpoint rotation ordering."""
    endpoints = get_ollama_endpoints()
    assert len(endpoints) >= 3
    # First priority must be Stevens-Mini-2 (192.168.8.103)
    assert "192.168.8.103:11434" in endpoints[0]
    # Second priority must be mac-m1-max (192.168.8.22)
    assert "192.168.8.22:11434" in endpoints[1]
    # Third priority must be 520c (192.168.8.181)
    assert "192.168.8.181:11434" in endpoints[2]
    # mac-m3-max (192.168.8.31) must NOT be in the standard list
    for ep in endpoints:
        assert "192.168.8.31" not in ep

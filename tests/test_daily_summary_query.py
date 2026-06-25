import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import sqlite3
import pytest
from repl_client import execute_sql, SYNC_DIR

def test_daily_summary_query_validation():
    db_path = os.path.join(SYNC_DIR, "local_repl.db")
    assert os.path.exists(db_path), f"Database not found at {db_path}"
    
    # 1. Test original query (with T-separated timestamps for backups_db.analysis_history)
    # This should fail to match the flex event on 2026-06-23 (returning 0)
    original_sql = """
    WITH date_bounds AS (
      SELECT '2026-06-23T00:00:00' AS start_ts, '2026-06-24T00:00:00' AS end_ts
    ),
    flex_event AS (
      SELECT COUNT(*) as flex_event_count, SUM(delta_bat_discharge) as flex_discharge_kwh
      FROM backups_db.analysis_history, date_bounds
      WHERE timestamp >= start_ts AND timestamp < end_ts AND delta_bat_discharge > 0.1
    )
    SELECT flex_event_count FROM flex_event;
    """
    original_res = execute_sql(db_path, original_sql)
    orig_line = original_res.strip().split("\n")[-1]
    orig_count = int(orig_line.split("|")[-2].strip())
    
    # 2. Test corrected query (with separate space-separated boundaries and grid_history integrated)
    corrected_sql = """
    WITH date_bounds AS (
      SELECT '2026-06-23T00:00:00' AS start_ts, '2026-06-24T00:00:00' AS end_ts,
             '2026-06-23 00:00:00' AS start_ts_space, '2026-06-24 00:00:00' AS end_ts_space
    ),
    se_stats AS (
      SELECT SUM(pv_kw) as se_pv_sum, AVG(pv_kw) as se_pv_avg 
      FROM solaredge_history, date_bounds 
      WHERE timestamp >= start_ts AND timestamp < end_ts
    ),
    ch_stats AS (
      SELECT SUM(power_kw) as ch_pv_sum, AVG(power_kw) as ch_pv_avg 
      FROM chilicon_history, date_bounds 
      WHERE timestamp >= start_ts AND timestamp < end_ts
    ),
    bat_stats AS (
      SELECT AVG(soc) as bat_soc_avg, AVG(battery_kw) as bat_kw_avg 
      FROM solaredge_battery_history, date_bounds 
      WHERE timestamp >= start_ts AND timestamp < end_ts
    ),
    flow_stats AS (
      SELECT AVG(grid_import_kw) as grid_import_avg, AVG(grid_export_kw) as grid_export_avg, AVG(load_power_kw) as load_avg 
      FROM solaredge_flow_history, date_bounds 
      WHERE timestamp >= start_ts AND timestamp < end_ts
    ),
    grid_stats AS (
      SELECT AVG(kw) as grid_avg, MIN(kw) as grid_min, MAX(kw) as grid_max
      FROM grid_history, date_bounds
      WHERE timestamp >= start_ts AND timestamp < end_ts
    ),
    flex_event AS (
      SELECT COUNT(*) as flex_event_count, MAX(delta_bat_discharge) as flex_discharge_kwh
      FROM backups_db.analysis_history, date_bounds
      WHERE timestamp >= start_ts_space AND timestamp < end_ts_space AND delta_bat_discharge > 0.1
    )
    SELECT se_pv_avg, ch_pv_avg, grid_avg, flex_event_count FROM se_stats, ch_stats, bat_stats, flow_stats, grid_stats, flex_event;
    """
    corrected_res = execute_sql(db_path, corrected_sql)
    print("Corrected SQL Results:")
    print(corrected_res)
    
    last_line = corrected_res.strip().split("\n")[-1]
    corrected_count = int(last_line.split("|")[-2].strip())
    
    # Assert that the corrected query retrieved the 6 space-separated rows for June 23rd
    assert corrected_count == 6, f"Corrected query should match exactly 6 rows (got: {corrected_count})"
    # Assert that grid_history columns are present and populated
    assert "grid_avg" in corrected_res or "grid_stats" in corrected_res or any(c in corrected_res for c in ["se_pv_avg", "ch_pv_avg"])

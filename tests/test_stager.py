"""Unit tests verifying the Jetson Edge AI Stager logic.

Tests baseline metric calculations, range-based aggregation, and baseline
generation prompt construction.
"""

import datetime
import os
import sys
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch
import pytest

# Add parent directory to path so we can import stage_local_summary
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import stage_local_summary


def test_calculate_baseline_metrics() -> None:
    """Verifies that calculate_baseline_metrics computes standard metrics correctly."""
    # (hour_str, avg_kw, min_kw, max_kw, median_kw, se_avg, se_max,
    #  se_energy, bat_avg, bat_soc, ch_avg, ch_max, ch_energy)
    records: List[Tuple[Any, ...]] = [
        # Grid import, SolarEdge generates, battery charging, Chillicon generates
        ("2026-05-28 12:00:00", 1.5, 0.5, 2.0, 1.5, 2.0, 2.5, 2.0, -0.5, 80.0, 0.5, 0.8, 0.5),
        # Grid export (negative avg_kw), SolarEdge generates, battery discharging (positive bat_avg)
        ("2026-05-28 13:00:00", -1.0, -1.5, -0.5, -1.0, 3.0, 3.5, 3.0, 1.0, 75.0, 0.8, 1.0, 0.8),
    ]

    metrics: Dict[str, float] = stage_local_summary.calculate_baseline_metrics(records)

    # Total grid import: 1.5 kWh
    # Total grid export: 1.0 kWh
    # SolarEdge generated: 2.0 + 3.0 = 5.0 kWh
    # Battery discharged: 1.0 kWh
    # Battery charged: 0.5 kWh
    # Chillicon generated: 0.5 + 0.8 = 1.3 kWh
    # Inferred Chillicon: for grid export row (avg_kw = -1.0):
    #   grid_export_rate = 1.0
    #   inferred = 1.0 - 3.0 - max(0.0, 1.0) = 1.0 - 3.0 - 1.0 = -3.0 (not > 0) -> inferred = 0.0
    # Peak grid import: 2.0 kW
    # Peak grid export: 1.5 kW
    # Peak SolarEdge: 3.5 kW
    # Peak Chillicon: 1.0 kW

    assert metrics["total_imported"] == 1.5
    assert metrics["total_exported"] == 1.0
    assert metrics["se_generated"] == 5.0
    assert metrics["battery_discharged"] == 1.0
    assert metrics["battery_charged"] == 0.5
    assert metrics["chilicon_generated"] == 1.3
    assert metrics["peak_grid_import"] == 2.0
    assert metrics["peak_grid_export"] == 1.5
    assert metrics["peak_se_pv"] == 3.5
    assert metrics["peak_chilicon_pv"] == 1.0

    # Net credit calculation:
    # import_cost = 1.5 * 0.19 = 0.285
    # export_credit = 1.0 * 0.19 = 0.190
    # flex_bonus = 1.0 * 0.31 = 0.31
    # net_credit = 0.190 - 0.285 + 0.31 = 0.215
    assert abs(metrics["net_credit"] - 0.215) < 1e-5

    # Home consumption calculation:
    # total_solar = 5.0 + 1.3 = 6.3
    # home = 6.3 + 1.5 - 1.0 + 1.0 - 0.5 = 7.3
    assert abs(metrics["home_consumption"] - 7.3) < 1e-5


@patch("stage_local_summary.generate_hourly_summaries")
def test_calculate_baseline_metrics_for_range(mock_gen_summaries: MagicMock) -> None:
    """Verifies filtering of hourly CSV logs inside a specific datetime range."""
    # Mock CSV string output from generate_hourly_summaries
    mock_csv: str = (
        "Hour,Avg_kW,Min_kW,Max_kW,Median_kW,SE_Avg_kW,SE_Max_kW,SE_Energy_kWh,"
        "Battery_Avg_kW,Battery_SoC,Chillicon_Avg_kW,Chillicon_Max_kW,Chillicon_Energy_kWh,"
        "Load_Avg_kW,Load_Max_kW,Load_Energy_kWh\n"
        "2026-05-28 11:00:00,1.0,0.5,1.5,1.0,1.5,2.0,1.5,0.0,90.0,0.4,0.5,0.4,1.9,2.5,1.9\n"
        "2026-05-28 12:00:00,1.5,0.5,2.0,1.5,2.0,2.5,2.0,-0.5,80.0,0.5,0.8,0.5,2.0,2.8,2.0\n"
        "2026-05-28 13:00:00,-1.0,-1.5,-0.5,-1.0,3.0,3.5,3.0,1.0,75.0,0.8,1.0,0.8,1.2,2.0,1.2\n"
        "2026-05-28 14:00:00,2.0,1.0,3.0,2.0,1.0,1.5,1.0,0.0,70.0,0.2,0.3,0.2,2.8,3.2,2.8\n"
    )
    mock_gen_summaries.return_value = mock_csv

    start_dt: datetime.datetime = datetime.datetime(2026, 5, 28, 12, 0, 0)
    end_dt: datetime.datetime = datetime.datetime(2026, 5, 28, 13, 0, 0)

    # Range calculation should only include 12:00 and 13:00 records
    metrics: Dict[str, float] = stage_local_summary.calculate_baseline_metrics_for_range(
        start_dt, end_dt
    )

    assert metrics["total_imported"] == 1.5
    assert metrics["total_exported"] == 1.0
    assert metrics["se_generated"] == 5.0


@patch("stage_local_summary.query_local_ollama")
@patch("stage_local_summary.calculate_baseline_metrics_for_range")
@patch("os.path.exists")
@patch("builtins.open")
def test_generate_local_baseline(
    mock_open: MagicMock,
    mock_exists: MagicMock,
    mock_calc_range: MagicMock,
    mock_ollama: MagicMock,
) -> None:
    """Verifies construction of the baseline prompt and query to local Ollama."""
    mock_exists.return_value = True
    
    # Mock reading the gemma_prompt.txt template file
    mock_file = MagicMock()
    mock_file.read.return_value = "Stats: {total_imported:.3f} | {day_date}"
    mock_open.return_value.__enter__.return_value = mock_file

    # Mock statistics output
    mock_calc_range.return_value = {
        "total_imported": 1.234,
        "total_exported": 0.5,
        "se_generated": 2.5,
        "chilicon_generated": 1.0,
        "inferred_chilicon": 0.0,
        "battery_charged": 0.5,
        "battery_discharged": 0.8,
        "net_credit": -0.15,
        "peak_grid_import": 1.8,
        "peak_se_pv": 3.0,
        "home_consumption": 4.2,
    }

    mock_ollama.return_value = "Baseline output from Gemma."

    baseline_dt: datetime.datetime = datetime.datetime(2026, 6, 8, 12, 0, 0)
    summary: str = stage_local_summary.generate_local_baseline(baseline_dt)

    assert summary == "Baseline output from Gemma."
    # Ensure correct prompt template path is opened
    expected_path: str = os.path.join(stage_local_summary.SCRIPT_DIR, "gemma_prompt.txt")
    mock_open.assert_called_with(expected_path, "r", encoding="utf-8")
    
    # Ensure the stats were computed for range (24h prior)
    start_dt: datetime.datetime = baseline_dt - datetime.timedelta(hours=24)
    mock_calc_range.assert_called_with(start_dt, baseline_dt)
    
    # Ensure Ollama was queried with the formatted prompt
    formatted_prompt = "Stats: 1.234 | 2026-06-08"
    mock_ollama.assert_called_with(formatted_prompt, stage_local_summary.DEFAULT_MODEL)

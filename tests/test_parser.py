"""Hermetic Test Suite for the EMU-2 Grid Dashboard.

This module contains comprehensive, hermetic unit tests that verify
the behavior of dashboard components (XML parsing, bitwise math, text wrapping)
as well as integration-level retry loops (PySerial polling, Vertex AI API calls)
using mock objects to ensure zero external dependencies.
"""

import pytest
import os
import json
import sys
import tempfile
import datetime
import serial
import unittest.mock

# Add the parent directory to the path so we can import dashboard
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import patch, MagicMock
from dashboard import GridDashboard

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_hex_to_signed_int_positive():
    """Test that a standard positive hex value decodes correctly."""
    dashboard = GridDashboard()
    result = dashboard.hex_to_signed_int("00000A2C")
    assert result == 2604

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_hex_to_signed_int_negative():
    """Test that a 2's complement negative hex value decodes correctly."""
    dashboard = GridDashboard()
    result = dashboard.hex_to_signed_int("FFFFF12B")
    assert result == -3797

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_hex_to_signed_int_zero():
    """Test that zero decodes correctly."""
    dashboard = GridDashboard()
    result = dashboard.hex_to_signed_int("00000000")
    assert result == 0

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_process_chunk_robustness():
    """Ensure process_chunk does not crash on completely malformed XML."""
    dashboard = GridDashboard()
    bad_xml = "<InstantaneousDemand><Demand>00000A2C</Demand></WrongTag>"
    try:
        dashboard.process_chunk(bad_xml)
    except Exception as e:
        pytest.fail(f"process_chunk raised an exception instead of catching it: {e}")

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_wrap_text():
    """Test that text wrapping maintains lists and paragraph boundaries."""
    dashboard = GridDashboard()
    # Test unstructured paragraph wrap
    long_text = "This is a very long text that should be wrapped because it exceeds the eighty character limit that we specified in our function call."
    wrapped = dashboard.wrap_text(long_text, width=80)
    for line in wrapped.split('\n'):
        assert len(line) <= 80

    # Test structured list wrap
    structured_text = "- Item 1: This is a very long item that should be indented correctly on the next line when it wraps."
    wrapped_structured = dashboard.wrap_text(structured_text, width=40)
    lines = wrapped_structured.split('\n')
    assert lines[0].startswith("- Item 1:")
    assert lines[1].startswith("  ") # Should be indented by two spaces

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_load_history():
    """Test loading history from CSV with mocked file and robust parsing."""
    dashboard = GridDashboard()
    dashboard.usage = []
    dashboard.timestamps = []
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        # Valid row 1 hour ago
        valid_time = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        f.write(f"{valid_time},1.234\n")
        # Corrupted row with null bytes
        f.write(f"{valid_time}\x00,bad_data\x00\n")
        # Valid row 2 hours ago
        valid_time2 = (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat()
        f.write(f"{valid_time2},-0.500\n")
        temp_path = f.name
        
    dashboard.history_file = temp_path
    
    try:
        dashboard.load_history()
        assert len(dashboard.usage) == 2
        assert dashboard.usage[0] == 1.234
        assert dashboard.usage[1] == -0.500
    finally:
        os.remove(temp_path)

@patch('serial.Serial')
@patch.object(GridDashboard, '__init__', lambda x: None)
@patch('time.sleep', return_value=None)
def test_read_serial_exception_recovery(mock_sleep, mock_serial):
    """Hermetic test proving serial polling recovers from SerialException."""
    dashboard = GridDashboard()
    dashboard.running = True
    dashboard.update_ui_text = MagicMock()
    dashboard.find_emu2_port = MagicMock(return_value='/dev/ttyACM0')
    
    mock_ser_instance = MagicMock()
    mock_ser_instance.is_open = True
    
    def side_effect(*args, **kwargs):
        dashboard.running = False
        raise serial.SerialException("Spoofed disconnect")
        
    mock_ser_instance.read.side_effect = side_effect
    mock_serial.return_value = mock_ser_instance
    
    dashboard.read_serial()
    
    mock_sleep.assert_called_with(5)

@patch('google.genai.Client')
@patch('time.sleep', return_value=None)
@patch.object(GridDashboard, '__init__', lambda x: None)
def test_fetch_gemini_summary_backoff(mock_sleep, mock_genai_client):
    """Hermetic test proving Gemini API native exponential backoff."""
    dashboard = GridDashboard()
    dashboard.local_llm = False
    dashboard.usage = [1.0] * 20
    dashboard.timestamps = [datetime.datetime.now()] * 20
    dashboard.solaredge_api_key = None
    dashboard.solaredge_site_id = None
    dashboard.last_summary_time = None
    dashboard.summary_cache_file = "/dev/null"
    dashboard.update_background_summary = MagicMock()
    dashboard.after = MagicMock()
    
    dashboard.generate_hourly_summaries = MagicMock(return_value="Hour,Avg_kW,Min_kW,Max_kW,Median_kW,SE_Avg_kW,SE_Max_kW,SE_Energy_kWh\n2026-05-26 12:00,1.5,1.5,1.5,1.5,0.0,0.0,0.0")
    
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}):
        mock_client_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Spoofed summary"
        
        mock_client_instance.models.generate_content.side_effect = [
            Exception("Network error 1"),
            Exception("Network error 2"),
            Exception("Network error 3"),
            mock_response
        ]
        mock_genai_client.return_value = mock_client_instance
        
        original_open = open
        def mock_open_file(file, *args, **kwargs):
            if 'gemini_prompt.txt' in str(file):
                return unittest.mock.mock_open(read_data="{csv_data} {current_date_time} {last_data_time}")()
            if 'gemini_summary.json' in str(file) or '/dev/null' in str(file):
                return unittest.mock.mock_open()()
            return original_open(file, *args, **kwargs)
            
        with patch('builtins.open', side_effect=mock_open_file):
            with patch('os.path.exists', return_value=True):
                dashboard.fetch_gemini_summary()
        
        mock_sleep.assert_any_call(2)
        mock_sleep.assert_any_call(4)
        mock_sleep.assert_any_call(8)
        
        dashboard.after.assert_called_with(0, dashboard.update_background_summary, "Spoofed summary")

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_load_solaredge_history():
    """Test loading SolarEdge history from CSV."""
    dashboard = GridDashboard()
    dashboard.solar_off = False
    dashboard.se_power = []
    dashboard.se_timestamps = []
    dashboard.se_battery_history_file = "/dev/null"
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        valid_time = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        f.write(f"{valid_time},1.500\n")
        f.write(f"{valid_time}\x00,bad_data\x00\n")
        temp_path = f.name
        
    dashboard.se_history_file = temp_path
    try:
        dashboard.load_solaredge_history()
        assert len(dashboard.se_power) == 1
        assert dashboard.se_power[0] == 1.500
    finally:
        os.remove(temp_path)

@patch.object(GridDashboard, '__init__', lambda x: None)
@patch('urllib.request.urlopen')
def test_fetch_solaredge_data(mock_urlopen):
    """Test fetching and parsing SolarEdge API overview response."""
    dashboard = GridDashboard()
    dashboard.solaredge_api_key = "fake_key"
    dashboard.solaredge_site_id = "fake_id"
    dashboard.se_power = []
    dashboard.se_timestamps = []
    dashboard.se_battery_timestamps = []
    dashboard.se_battery_power = []
    dashboard.se_battery_soc = []
    dashboard.max_points = 5
    dashboard.after = MagicMock()
    dashboard.status_label = MagicMock()
    dashboard.sub_status_label = MagicMock()
    dashboard.se_battery_history_file = "/dev/null"
    
    # Mock status label cget
    dashboard.status_label.cget.side_effect = lambda attr: "white" if attr == "fg" else "Waiting..."
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        temp_path = f.name
    dashboard.se_history_file = temp_path
    
    # Mock response JSON
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"siteCurrentPowerFlow": {"pv": {"currentPower": 1.2}, "storage": {"currentPower": 0.0, "chargeLevel": 100.0, "status": "Idle"}}}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    
    # Mock datetime hour to be inside daytime window (12:00 PM)
    mock_now = datetime.datetime(2026, 5, 26, 12, 0, 0)
    try:
        with patch('datetime.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.fromisoformat = datetime.datetime.fromisoformat
            
            dashboard.fetch_solaredge_data()
            
            assert len(dashboard.se_power) == 1
            assert dashboard.se_power[0] == 1.200 # 1.2 kW
            dashboard.after.assert_called()
    finally:
        os.remove(temp_path)

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_generate_hourly_summaries_with_solaredge():
    """Test hourly summaries combine both grid history and SolarEdge history."""
    dashboard = GridDashboard()
    dashboard.solar_off = False
    dashboard.se_battery_history_file = "/dev/null"
    dashboard.chilicon_off = True
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f_grid:
        valid_time = "2026-05-26T12:00:00"
        f_grid.write(f"{valid_time},2.000\n")
        grid_path = f_grid.name
        
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f_se:
        f_se.write(f"{valid_time},1.500\n")
        se_path = f_se.name
        
    dashboard.history_file = grid_path
    dashboard.se_history_file = se_path
    
    try:
        csv_data = dashboard.generate_hourly_summaries()
        lines = csv_data.split('\n')
        # Header + 1 data line
        assert len(lines) == 2
        assert lines[0] == "Hour,Avg_kW,Min_kW,Max_kW,Median_kW,SE_Avg_kW,SE_Max_kW,SE_Energy_kWh,Battery_Avg_kW,Battery_SoC,Chillicon_Avg_kW,Chillicon_Max_kW,Chillicon_Energy_kWh"
        assert "2026-05-26 12:00,2.000,2.000,2.000,2.000,1.500,1.500,1.500,0.000,0.0,0.000,0.000,0.000" in lines[1]
    finally:
        os.remove(grid_path)
        os.remove(se_path)

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_solar_off_flag():
    """Test that solar_off flag suppresses SolarEdge loop and history loading."""
    dashboard = GridDashboard()
    dashboard.solar_off = True
    dashboard.se_history_file = "/dev/null"
    dashboard.se_power = []
    dashboard.se_timestamps = []
    
    dashboard.load_solaredge_history()
    assert len(dashboard.se_power) == 0
    
    dashboard.start_solaredge_loop()
    assert 'solaredge_thread' not in dashboard.__dict__

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_load_credentials():
    """Test loading credentials from JSON config."""
    dashboard = GridDashboard()
    dashboard.solaredge_api_key = None
    dashboard.solaredge_site_id = None
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        json.dump({"api_key": "json_key", "site_id": "json_id"}, f)
        temp_path = f.name
        
    try:
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', unittest.mock.mock_open(read_data=open(temp_path).read())):
                dashboard.load_credentials()
                assert dashboard.solaredge_api_key == "json_key"
                assert dashboard.solaredge_site_id == "json_id"
    finally:
        os.remove(temp_path)


# --- Additional Tests for Jetson Edge Server Architecture ---

def test_parse_timestamp():
    """Test parse_timestamp parses multiple valid format naive datetimes."""
    from stage_local_summary import parse_timestamp as local_parse_ts
    
    # ISO Format
    ts1 = local_parse_ts("2026-05-30T10:06:13.120731")
    assert ts1 is not None
    assert ts1.year == 2026 and ts1.month == 5 and ts1.day == 30 and ts1.hour == 10 and ts1.minute == 6
    
    # Custom format with spaces
    ts2 = local_parse_ts("2026-05-30 10:06:13")
    assert ts2 is not None
    assert ts2.year == 2026 and ts2.month == 5 and ts2.day == 30 and ts2.hour == 10 and ts2.minute == 6


@patch('urllib.request.urlopen')
def test_fetch_weather_mock(mock_urlopen):
    """Test fetch_weather mocks Open-Meteo REST API call and parses it correctly."""
    from stage_local_summary import fetch_weather
    
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"daily_units":{"temperature_2m_max":"C"},"daily":{"time":["2026-05-30"],"temperature_2m_max":[18.5],"cloud_cover_mean":[45.0]}}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    
    temp, cloud = fetch_weather()
    assert temp == 18.5
    assert cloud == 45.0


def test_calculate_solar_correlation():
    """Test calculate_solar_correlation computes accurate Pearson correlation."""
    from stage_local_summary import calculate_solar_correlation
    import math
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f_se, \
         tempfile.NamedTemporaryFile(mode='w', delete=False) as f_ch:
        
        # Write matching timestamps with perfect positive linear correlation (r = 1.0)
        base_time = datetime.datetime(2026, 5, 30, 12, 0)
        for i in range(10):
            ts = (base_time + datetime.timedelta(minutes=i*15)).isoformat()
            f_se.write(f"{ts},{1.0 + i}\n")
            f_ch.write(f"{ts},{2.0 + i * 2},{50.0}\n")
            
        se_path = f_se.name
        ch_path = f_ch.name
        
    try:
        r = calculate_solar_correlation(se_path, ch_path)
        assert abs(r - 1.0) < 1e-5
    finally:
        os.remove(se_path)
        os.remove(ch_path)


@patch('urllib.request.urlopen')
@patch('stage_local_summary.calculate_deltas')
@patch('stage_local_summary.calculate_grid_stats')
@patch('stage_local_summary.calculate_solar_tod_stats')
@patch('stage_local_summary.calculate_solar_correlation')
@patch('stage_local_summary.fetch_weather')
@patch('stage_local_summary.DEFAULT_MODEL', 'gemma2:2b')
def test_run_analysis_workflow(mock_weather, mock_corr, mock_tod, mock_grid, mock_deltas, mock_urlopen):
    """Test run_analysis_workflow coordinates stats, weather, and local Ollama queries."""
    from stage_local_summary import run_analysis_workflow
    
    mock_weather.return_value = (16.0, 50.0)
    mock_corr.return_value = 0.95
    mock_tod.return_value = (2.0, 0.2)
    mock_grid.return_value = (1.5, 0.5)
    mock_deltas.return_value = {
        "delta_import": 1.2,
        "delta_export": 0.0,
        "delta_peak": 2.5,  # (2.5 - 1.5)/0.5 = 2.0
        "delta_solar": 3.0,
        "delta_bat_charge": 0.5,
        "delta_bat_discharge": 0.4
    }
    
    # Mock Ollama API response
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"response":"System operating within baseline limits"}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    
    result = run_analysis_workflow("2026-05-30 10:00:00", "Baseline Summary Text")
    assert result is not None
    assert "response" in result
    assert result["response"] == "System operating within baseline limits"

"""Unit tests for the Jetson background DFT loop and local caching logic.

Verifies that the stager correctly calculates and serves the spectrum, and
the dashboard correctly utilizes cached data or falls back to local math.
"""

import sys
import os
import json
import tempfile
import datetime
from unittest.mock import patch, MagicMock
import pytest

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import dashboard
import stage_local_summary


@patch.object(dashboard.GridDashboard, '__init__', lambda x: None)
def test_dashboard_bypasses_local_math_on_cache_hit() -> None:
    """Verify GridDashboard returns cached spectrum directly when available in JSON."""
    db = dashboard.GridDashboard()
    db._data_lock = MagicMock()
    db.summary_cache_file = "/dev/null"
    
    # Pre-populate cached spectrum data
    mock_spectrum = {
        "freqs": [1.0, 2.0],
        "grid_amp": [0.5, 0.6],
        "solar_amp": [1.5, 1.6],
        "expected_solar_amp": [1.0, 1.1],
        "consumption_amp": [2.0, 2.1]
    }
    db.cached_full_history_spectrum = mock_spectrum

    # Patch spectral.align_and_compute_spectra to verify it is NOT called
    with patch('dashboard_modules.spectral.align_and_compute_spectra') as mock_spectral:
        freqs, grid_amp, solar_amp, expected, consumption = db.align_and_compute_spectrum()
        
        mock_spectral.assert_not_called()
        assert freqs == [1.0, 2.0]
        assert grid_amp == [0.5, 0.6]
        assert solar_amp == [1.5, 1.6]
        assert expected == [1.0, 1.1]
        assert consumption == [2.0, 2.1]


@patch.object(dashboard.GridDashboard, '__init__', lambda x: None)
def test_dashboard_calculates_local_math_on_cache_miss() -> None:
    """Verify GridDashboard falls back to local math when cache is empty."""
    db = dashboard.GridDashboard()
    db._data_lock = MagicMock()
    db.timestamps = [datetime.datetime.now()]
    db.usage = [1.0]
    db.se_timestamps = []
    db.se_power = []
    db.chilicon_timestamps = []
    db.chilicon_power = []
    db.weather_map = {}
    db.chilicon_off = True
    db.cached_full_history_spectrum = {}

    # Patch spectral.align_and_compute_spectra to return mock values and verify it IS called
    with patch('dashboard_modules.spectral.align_and_compute_spectra') as mock_spectral:
        mock_spectral.return_value = ([0.1], [0.2], [0.3], [0.4], [0.5])
        
        freqs, grid_amp, _, _, _ = db.align_and_compute_spectrum()
        
        mock_spectral.assert_called_once()
        assert freqs == [0.1]
        assert grid_amp == [0.2]


def test_jetson_background_math_calculation() -> None:
    """Verify run_full_history_math populates cached_full_history_data correctly."""
    # Reset cached data
    stage_local_summary.cached_full_history_data = {}
    
    # Create mock files
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f_grid, \
         tempfile.NamedTemporaryFile(mode='w', delete=False) as f_se, \
         tempfile.NamedTemporaryFile(mode='w', delete=False) as f_ch:
        
        base_time = datetime.datetime.now() - datetime.timedelta(days=1)
        for i in range(10):
            ts = (base_time + datetime.timedelta(hours=i)).isoformat()
            f_grid.write(f"{ts},1.5\n")
            f_se.write(f"{ts},1.0\n")
            f_ch.write(f"{ts},0.5\n")
            
        grid_path = f_grid.name
        se_path = f_se.name
        ch_path = f_ch.name

    try:
        # Patch paths in stage_local_summary
        with patch('stage_local_summary.GRID_DB', grid_path), \
             patch('stage_local_summary.SE_HISTORY', se_path), \
             patch('stage_local_summary.CHILICON_HISTORY', ch_path), \
             patch('dashboard_modules.weather.fetch_historical_weather', return_value={}):
            
            stage_local_summary.run_full_history_math()
            
            # Verify cached full history dict has been populated
            assert stage_local_summary.cached_full_history_data != {}
            assert "freqs" in stage_local_summary.cached_full_history_data
            assert "grid_amp" in stage_local_summary.cached_full_history_data
            assert len(stage_local_summary.cached_full_history_data["freqs"]) == 400
    finally:
        os.remove(grid_path)
        os.remove(se_path)
        os.remove(ch_path)


@patch('stage_local_summary.run_analysis_workflow')
def test_analyze_endpoint_returns_spectrum(mock_workflow) -> None:
    """Verify HTTP request handler returns the cached spectrum under full_history_spectrum."""
    mock_workflow.return_value = {"response": "mocked text", "metrics": {}}
    
    # Pre-populate cached spectrum data
    stage_local_summary.cached_full_history_data = {
        "freqs": [1.0, 2.0],
        "grid_amp": [0.5, 0.6],
        "solar_amp": [1.5, 1.6],
        "expected_solar_amp": [1.0, 1.1],
        "consumption_amp": [2.0, 2.1]
    }
    
    # Mock Handler setup
    handler = stage_local_summary.AnalyzeHTTPRequestHandler
    mock_wfile = MagicMock()
    mock_rfile = MagicMock()
    mock_rfile.read.return_value = b'{"baseline_timestamp": "2026-06-04 12:00:00"}'
    
    # Initialize the handler
    mock_server = MagicMock()
    req_handler = handler.__new__(handler)
    req_handler.rfile = mock_rfile
    req_handler.wfile = mock_wfile
    req_handler.headers = {"Content-Length": str(len(mock_rfile.read.return_value))}
    req_handler.path = '/api/analyze'
    req_handler.server = mock_server
    req_handler.client_address = ('127.0.0.1', 12345)
    
    # Mock self.send_response, send_header, end_headers
    req_handler.send_response = MagicMock()
    req_handler.send_header = MagicMock()
    req_handler.end_headers = MagicMock()
    
    # Call do_POST
    req_handler.do_POST()
    
    # Assert JSON payload was written to wfile
    mock_wfile.write.assert_called_once()
    sent_data = json.loads(mock_wfile.write.call_args[0][0].decode('utf-8'))
    
    assert "full_history_spectrum" in sent_data
    assert sent_data["full_history_spectrum"]["freqs"] == [1.0, 2.0]
    assert sent_data["response"] == "mocked text"

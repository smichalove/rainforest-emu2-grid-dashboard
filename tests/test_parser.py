"""Hermetic Test Suite for the EMU-2 Grid Dashboard.

This module contains comprehensive, hermetic unit tests that verify
the behavior of dashboard components (XML parsing, bitwise math, text wrapping)
as well as integration-level retry loops (PySerial polling, Vertex AI API calls)
using mock objects to ensure zero external dependencies.
"""

import pytest
import os
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
    dashboard.usage = [1.0] * 20
    dashboard.timestamps = [datetime.datetime.now()] * 20
    dashboard.last_summary_time = None
    dashboard.summary_cache_file = "/dev/null"
    dashboard.update_background_summary = MagicMock()
    dashboard.after = MagicMock()
    
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
        
        with patch('builtins.open', unittest.mock.mock_open(read_data="{csv_data} {current_date_time} {last_data_time}")):
            with patch('os.path.exists', return_value=True):
                dashboard.fetch_gemini_summary()
        
        mock_sleep.assert_any_call(2)
        mock_sleep.assert_any_call(4)
        mock_sleep.assert_any_call(8)
        
        dashboard.after.assert_called_with(0, dashboard.update_background_summary, "Spoofed summary")

import pytest
import os
import sys

# Add the parent directory to the path so we can import dashboard
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import patch
from dashboard import GridDashboard

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_hex_to_signed_int_positive():
    """Test that a standard positive hex value decodes correctly."""
    dashboard = GridDashboard()
    
    # 0x00000A2C = 2604
    result = dashboard.hex_to_signed_int("00000A2C")
    assert result == 2604

@patch.object(GridDashboard, '__init__', lambda x: None)
def test_hex_to_signed_int_negative():
    """Test that a 2's complement negative hex value decodes correctly."""
    dashboard = GridDashboard()
    
    # 0xFFFFF12B is negative 3797 in 32-bit two's complement
    # To check: (0xFFFFF12B ^ 0xFFFFFFFF) + 1 = 0x0ED4 + 1 = 0x0ED5 = 3797 -> -3797
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
    
    # Missing tags, bad XML structure
    bad_xml = "<InstantaneousDemand><Demand>00000A2C</Demand></WrongTag>"
    
    # Should safely catch ET.ParseError and return without raising an exception
    try:
        dashboard.process_chunk(bad_xml)
    except Exception as e:
        pytest.fail(f"process_chunk raised an exception instead of catching it: {e}")

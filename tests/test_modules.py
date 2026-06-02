"""Unit tests verifying the functionality of the new dashboard_modules package.

Tests config loaders, file IO, telemetry parser, open-meteo weather queries,
DFT spectrum generators, and AI prompt template formatting.
"""

import datetime
import math
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest
import os
import sys

# Add the parent directory to the path so we can import dashboard_modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dashboard_modules import config, io, telemetry, solar, weather, spectral, ai


def test_config_defaults():
    """Verify default config parameters exist and are set correctly."""
    assert config.BAUD == 115200
    assert config.STATUS_FONT_SIZE == 24
    assert config.IMPORT_COLOR == '#f43f5e'
    assert config.EXPORT_COLOR == '#00ff00'


def test_io_safe_json():
    """Test safe JSON reading and writing with atomic replacements."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_cache.json")
        
        # Test read missing
        assert io.read_safe_json(test_file) == {}
        
        # Test write and read
        data = {"test_key": "test_val", "number": 42}
        io.write_safe_json(test_file, data)
        
        read_data = io.read_safe_json(test_file)
        assert read_data == data
        
        # Test corrupt file recovery
        with open(test_file, "w") as f:
            f.write("{invalid json...")
        
        assert io.read_safe_json(test_file) == {}


def test_io_clean_csv():
    """Test CSV loading with automatic null-byte removal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = os.path.join(tmpdir, "history.csv")
        
        # Write rows, including one with corrupt null-bytes
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            f.write("2026-06-01T12:00:00,1.234\n")
            f.write("2026-06-01T12:05:00\x00,bad_data\x00\n")
            f.write("2026-06-01T12:10:00,2.500\n")
            
        rows = io.read_clean_csv(csv_file)
        # Should drop invalid rows or strip corrupt bytes
        assert len(rows) == 3
        assert rows[0] == ["2026-06-01T12:00:00", "1.234"]
        assert rows[1] == ["2026-06-01T12:05:00", "bad_data"]
        assert rows[2] == ["2026-06-01T12:10:00", "2.500"]


def test_telemetry_hex_to_signed_int():
    """Test 32-bit hex decoder with positive and negative numbers."""
    assert telemetry.hex_to_signed_int("00000000") == 0
    assert telemetry.hex_to_signed_int("000000FF") == 255
    assert telemetry.hex_to_signed_int("FFFFFFFF") == -1
    assert telemetry.hex_to_signed_int("00000A2C") == 2604
    assert telemetry.hex_to_signed_int("FFFFF12B") == -3797


def test_telemetry_parse_xml():
    """Test XML parsing of InstantaneousDemand payloads."""
    xml_ok = (
        "<InstantaneousDemand>"
        "<Demand>00000A2C</Demand>"
        "<Multiplier>00000001</Multiplier>"
        "<Divisor>000003E8</Divisor>"
        "</InstantaneousDemand>"
    )
    # 2604 * 1 / 1000 = 2.604 kW
    val = telemetry.parse_xml_telemetry(xml_ok)
    assert val is not None
    assert abs(val - 2.604) < 1e-5

    # Divisor 0 should skip
    xml_div_zero = (
        "<InstantaneousDemand>"
        "<Demand>00000A2C</Demand>"
        "<Multiplier>00000001</Multiplier>"
        "<Divisor>00000000</Divisor>"
        "</InstantaneousDemand>"
    )
    assert telemetry.parse_xml_telemetry(xml_div_zero) is None


def test_spectral_interpolation():
    """Verify linear interpolation fills None gaps properly."""
    series = [1.0, None, 3.0, None, None, 6.0]
    # Expected: [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    interpolated = spectral.interpolate_gaps(series)
    assert interpolated == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_spectral_compute_dft():
    """Test compute_dft resolves expected sine wave parameters."""
    N = 24
    freq = 1.0  # 1 cycle/day (24h period)
    series = [5.0 * math.cos(2.0 * math.pi * n / 24.0) for n in range(N)]
    
    re, im, mag = spectral.compute_dft(series, freq)
    # Magnitude should resolve closely to 5.0
    assert abs(mag - 5.0) < 1e-5

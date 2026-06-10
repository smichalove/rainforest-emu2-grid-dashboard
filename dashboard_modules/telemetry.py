"""Rainforest EMU-2 serial communication, XML parsing, and grid history loading.

This module is designed to run in background threads on physical hardware while
supporting safe testing on development platforms.
"""

import datetime
import logging
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

# Local imports
from .io import read_clean_csv, write_csv_row
from . import db

# Lazy load serial only when needed to prevent crashes on systems without serial drivers
serial_module = None


def get_serial():
    """Lazy imports the serial module and its list_ports extension."""
    global serial_module
    if serial_module is None:
        import serial
        import serial.tools.list_ports
        serial_module = serial
    return serial_module


def find_emu2_port() -> str:
    """Dynamically searches for the Rainforest EMU-2 USB serial port.

    Returns:
        The device path of the serial port (e.g. '/dev/ttyACM0').
    """
    try:
        ser_mod = get_serial()
        ports = ser_mod.tools.list_ports.comports()
        for p in ports:
            if 'ACM' in p.device or 'Rainforest' in str(p.manufacturer):
                return p.device
    except Exception as e:
        logging.warning(f"Error during serial port scanning: {e}")
    return '/dev/ttyACM0'  # Default fallback


def hex_to_signed_int(hex_str: str, bits: int = 32) -> int:
    """Converts a hexadecimal string representation into a signed integer.

    Args:
        hex_str: The hexadecimal string to convert.
        bits: The bit-width of the target integer.

    Returns:
        The decoded signed integer value.
    """
    val: int = int(hex_str, 16)
    if (val & (1 << (bits - 1))) != 0:
        val = val - (1 << bits)
    return val


def parse_xml_telemetry(xml_data: str) -> Optional[float]:
    """Parses a single XML block containing grid demand telemetry.

    Args:
        xml_data: The XML string payload to parse.

    Returns:
        The parsed kilowatt (kW) usage as a float, or None if parsing fails.
    """
    try:
        root: ET.Element = ET.fromstring(xml_data)
        if root.tag == 'InstantaneousDemand':
            demand_elem = root.find('Demand')
            multiplier_elem = root.find('Multiplier')
            divisor_elem = root.find('Divisor')

            demand_text: Optional[str] = demand_elem.text if demand_elem is not None else None
            multiplier_text: Optional[str] = multiplier_elem.text if multiplier_elem is not None else None
            divisor_text: Optional[str] = divisor_elem.text if divisor_elem is not None else None

            if not demand_text or not multiplier_text or not divisor_text:
                logging.warning("Missing vital XML tags in InstantaneousDemand payload.")
                return None

            demand: int = hex_to_signed_int(demand_text)
            multiplier: int = int(multiplier_text, 16)
            divisor: int = int(divisor_text, 16)

            if divisor == 0:
                logging.warning("Received Divisor of 0, skipping calculation.")
                return None

            actual_kw: float = (demand * multiplier) / divisor
            return actual_kw
    except ET.ParseError as e:
        logging.warning(f"Fragmented XML dropped: {e}")
    except Exception as e:
        logging.error(f"Error parsing XML chunk: {e}")
    return None


def load_grid_history(filepath: str, cutoff_hours: int = 24) -> Tuple[List[datetime.datetime], List[float]]:
    """Loads historical measurements from database or CSV.

    Args:
        filepath: Filesystem path to the database or CSV history file.
        cutoff_hours: Number of hours in the past to load.

    Returns:
        A tuple of (timestamps, usage_in_kw).
    """
    if filepath.endswith('.db'):
        return db.query_history(filepath, cutoff_hours)

    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(hours=cutoff_hours)
    
    timestamps: List[datetime.datetime] = []
    usage: List[float] = []

    rows = read_clean_csv(filepath)
    for row in rows:
        if len(row) == 2:
            try:
                ts = datetime.datetime.fromisoformat(row[0])
                val = float(row[1])
                if ts > cutoff:
                    timestamps.append(ts)
                    usage.append(val)
            except Exception as e:
                logging.debug(f"Skipping corrupted history row: {row} - Error: {e}")
                
    return timestamps, usage


def log_grid_telemetry(filepath: str, timestamp: datetime.datetime, actual_kw: float) -> None:
    """Logs a single grid telemetry reading to the database or CSV.

    Args:
        filepath: Filesystem path to log telemetry (database or CSV).
        timestamp: Timestamp of the reading.
        actual_kw: The grid import/export in kW.
    """
    if filepath.endswith('.db'):
        db.insert_reading(filepath, timestamp.isoformat(), actual_kw)
    else:
        write_csv_row(filepath, [timestamp.isoformat(), f"{actual_kw:.3f}"])

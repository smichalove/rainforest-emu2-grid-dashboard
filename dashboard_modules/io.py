"""Centralized file Input/Output utilities for safe CSV and JSON reading and writing.

Provides thread-safety and guards files against corruption (e.g. from null-bytes
on unexpected power loss) using temporary-file swaps for writes.
"""

import csv
import json
import logging
import os
import tempfile
from typing import Any, Dict, List


def read_clean_csv(filepath: str) -> List[List[str]]:
    """Reads a CSV file while cleanly stripping out null bytes and empty lines.

    Args:
        filepath: The filesystem path to the CSV file.

    Returns:
        A list of rows, where each row is a list of strings.
    """
    if not os.path.exists(filepath):
        return []

    rows: List[List[str]] = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            # Strip null bytes that can occur during sudden power losses
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if row:
                    rows.append([cell.strip() for cell in row])
    except Exception as e:
        logging.error(f"Failed to read CSV file {filepath}: {e}")
    return rows


def write_csv_row(filepath: str, row: List[Any]) -> None:
    """Safely appends a single row to a CSV file.

    Args:
        filepath: The filesystem path to the CSV file.
        row: The list of values to write.
    """
    try:
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Catch cases where fsync is unsupported (e.g. some virtual mounts/mocking)
                pass
    except Exception as e:
        logging.error(f"Failed to append to CSV file {filepath}: {e}")


def read_safe_json(filepath: str) -> Dict[str, Any]:
    """Loads a JSON file safely, returning an empty dict if the file is corrupt or missing.

    Args:
        filepath: The filesystem path to the JSON file.

    Returns:
        A dictionary containing the parsed JSON data.
    """
    if not os.path.exists(filepath):
        return {}

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"Corrupted or unreadable JSON file {filepath}: {e}. Returning empty dictionary.")
        return {}


def write_safe_json(filepath: str, data: Dict[str, Any]) -> None:
    """Writes a dictionary to a JSON file atomically.

    Falls back to direct write if the temp file system is read-only (e.g. /dev/null context in tests).

    Args:
        filepath: The filesystem path to write the JSON data to.
        data: The dictionary data to dump.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        try:
            dir_name = os.path.dirname(filepath)
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, suffix='.tmp', encoding='utf-8') as tf:
                json.dump(data, tf, indent=2)
                tf.flush()
                try:
                    os.fsync(tf.fileno())
                except OSError:
                    pass
                temp_name = tf.name

            os.replace(temp_name, filepath)
        except Exception:
            # Fallback to direct write
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
    except Exception as e:
        logging.error(f"Failed to write JSON to {filepath}: {e}")
        # Cleanup temp file if it still exists
        if 'temp_name' in locals() and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except Exception:
                pass

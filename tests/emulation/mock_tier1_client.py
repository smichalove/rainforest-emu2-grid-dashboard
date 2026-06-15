"""Mock Tier 1 client simulator for microgrid telemetry ingestion.

Loads aligned telemetry data from the A/C spike JSON fixture, packages the
readings into structured 10-tuples required by the GridTelemetryClient, and
streams them to the Tier 2 Jetson gRPC server. Supports command-line parameters
to inject peak-load anomalies or battery failures.
"""

import argparse
import datetime
import json
import os
import sys
from typing import Dict, List, Optional, Tuple, Union

# Inject repository paths to allow imports to resolve correctly
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR: str = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, ROOT_DIR)

from dashboard_modules.grpc_client import GridTelemetryClient


def parse_datetime(dt_str: str) -> datetime.datetime:
    """Parses an ISO 8601 string into a datetime object.

    Args:
        dt_str: The ISO 8601 timestamp string.

    Returns:
        A datetime.datetime instance.
    """
    return datetime.datetime.fromisoformat(dt_str)


def load_fixture_data(
    fixture_path: str,
) -> Tuple[str, datetime.datetime, datetime.datetime, float, List[Dict[str, Union[str, float]]]]:
    """Loads the A/C spike fixture data from disk.

    Args:
        fixture_path: Path to the JSON fixture file.

    Returns:
        A tuple containing:
            - slice_id (str)
            - start_timestamp (datetime)
            - end_timestamp (datetime)
            - dft_period_hours (float)
            - readings (list of dicts)

    Raises:
        FileNotFoundError: If the fixture file does not exist.
        json.JSONDecodeError: If the fixture file is invalid JSON.
    """
    if not os.path.exists(fixture_path):
        raise FileNotFoundError(f"Fixture file not found: {fixture_path}")

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    slice_id: str = str(data["slice_id"])
    start_time: datetime.datetime = parse_datetime(data["start_timestamp"])
    end_time: datetime.datetime = parse_datetime(data["end_timestamp"])
    dft_period: float = float(data["dft_period_hours"])
    readings: List[Dict[str, Union[str, float]]] = data["readings"]

    return slice_id, start_time, end_time, dft_period, readings


def inject_peak_spike(readings: List[Dict[str, Union[str, float]]]) -> None:
    """Deliberately injects a high peak demand anomaly (>4.0 kW) into the readings.

    Modifies the telemetry readings in-place to exceed the z-score threshold.

    Args:
        readings: The list of telemetry dictionaries to modify.
    """
    # Find the middle reading and inject a massive peak load
    mid_idx: int = len(readings) // 2
    if mid_idx < len(readings):
        readings[mid_idx]["grid_usage_kw"] = 5.25  # Force high peak spike anomaly


def inject_battery_inefficiency(readings: List[Dict[str, Union[str, float]]]) -> None:
    """Deliberately injects battery charging inefficiency to simulate low RTE.

    Modifies the state-of-charge and battery power to simulate high power draw
    without corresponding state of charge increase.

    Args:
        readings: The list of telemetry dictionaries to modify.
    """
    # Force high discharge/charge rates with minimal state of charge change
    for reading in readings:
        reading["solaredge_battery_kw"] = 3.5  # Heavy battery discharge
        reading["solaredge_battery_soc"] = 25.0  # SoC gets stuck or drops rapidly


def run_client(
    host: str,
    port: int,
    use_mtls: bool,
    certs_dir: Optional[str],
    fixture_name: str,
    inject_spike: bool,
    inject_bat_fail: bool,
) -> None:
    """Runs the mock Tier 1 client to transmit telemetry to the gRPC server.

    Args:
        host: Hostname or IP of the gRPC server.
        port: Listening port of the gRPC server.
        use_mtls: Set to True to use secure mTLS.
        certs_dir: Directory containing mTLS certificates.
        fixture_name: Name of the JSON fixture file to load.
        inject_spike: Whether to inject a grid power peak spike.
        inject_bat_fail: Whether to inject a battery inefficiency anomaly.
    """
    fixture_path: str = os.path.join(SCRIPT_DIR, fixture_name)
    print(f"Loading telemetry slice fixture from: {fixture_path}")
    
    try:
        slice_id, start_time, end_time, dft_period, readings = load_fixture_data(fixture_path)
    except Exception as e:
        print(f"Failed to load fixture data: {e}")
        sys.exit(1)

    if inject_spike:
        print("Injecting peak grid demand spike anomaly...")
        inject_peak_spike(readings)
        slice_id = f"{slice_id}_spike_anomaly"

    if inject_bat_fail:
        print("Injecting battery round-trip inefficiency anomaly...")
        inject_battery_inefficiency(readings)
        slice_id = f"{slice_id}_battery_anomaly"

    # Convert dictionary readings to 10-tuples for GridTelemetryClient
    packed_readings: List[Tuple[datetime.datetime, float, float, float, float, float, float, float, float, float]] = []
    for r in readings:
        dt: datetime.datetime = parse_datetime(str(r["timestamp"]))
        packed_readings.append((
            dt,
            float(r["grid_usage_kw"]),
            float(r["solaredge_pv_kw"]),
            float(r["solaredge_battery_kw"]),
            float(r["solaredge_battery_soc"]),
            float(r["solaredge_load_kw"]),
            float(r["solaredge_import_kw"]),
            float(r["solaredge_export_kw"]),
            float(r["chilicon_pv_kw"]),
            float(r["chilicon_lifetime_wh"])
        ))

    # Construct the mock spectral metrics dictionary
    spectral_metrics = {
        "solar_24h_amp": 1.2,
        "solar_24h_peak_hour": 13.0,
        "grid_24h_amp": 0.8,
        "grid_12h_amp": 0.5,
        "grid_12h_peak_hour": 19.5,
        "grid_bimodal_ratio": 0.55,
        "grid_24h_snr_db": 12.4,
        "grid_12h_snr_db": 8.2,
        "solar_24h_snr_db": 15.1,
        "consumption_24h_snr_db": 10.3,
        "consumption_12h_snr_db": 7.5,
        "solar_slope": 0.05,
        "grid_slope": -0.02,
        "freqs": [0.0, 1.0, 2.0],
        "grid_amp_spec": [0.1, 0.5, 0.2],
        "solar_amp_spec": [0.0, 0.8, 0.1],
        "consumption_amp_spec": [0.2, 0.4, 0.3]
    }

    print(f"Connecting to gRPC server at {host}:{port} (mTLS={use_mtls})...")
    client = GridTelemetryClient(host=host, port=port, use_mtls=use_mtls, certs_dir=certs_dir)
    
    try:
        client.connect()
        print(f"Connected. Ingesting slice ID: {slice_id} with {len(packed_readings)} readings...")
        success, message = client.evaluate_slice(
            slice_id=slice_id,
            start_time=start_time,
            end_time=end_time,
            dft_period=dft_period,
            readings=packed_readings,
            spectral_metrics=spectral_metrics
        )
        print(f"Response success: {success}")
        print(f"Response message: {message}")
    except Exception as e:
        print(f"gRPC transaction failed: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate microgrid Tier 1 ingestion client.")
    parser.add_argument("--host", type=str, default="localhost", help="gRPC server hostname.")
    parser.add_argument("--port", type=int, default=50051, help="gRPC server port.")
    parser.add_argument("--insecure", action="store_true", help="Disable secure mTLS channel credentials.")
    parser.add_argument("--certs-dir", type=str, default=None, help="Directory containing client certs.")
    parser.add_argument("--fixture", type=str, default="ac_spike_fixture.json", help="JSON fixture filename.")
    parser.add_argument("--inject-spike", action="store_true", help="Inject grid peak demand spike anomaly.")
    parser.add_argument("--inject-battery-failure", action="store_true", help="Inject battery low-RTE anomaly.")
    
    args = parser.parse_args()
    
    run_client(
        host=args.host,
        port=args.port,
        use_mtls=not args.insecure,
        certs_dir=args.certs_dir,
        fixture_name=args.fixture,
        inject_spike=args.inject_spike,
        inject_bat_fail=args.inject_battery_failure
    )

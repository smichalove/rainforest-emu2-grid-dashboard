"""Integration test for the 3-Tier Edge-to-Cloud escalation flow.

Spins up the local stager gRPC daemon in insecure mode, pushes clean and anomalous
telemetry slices from the extracted A/C spike fixture, and asserts that anomaly rules,
ReAct database querying, and cloud mock escalation operate correctly.
"""

import datetime
import json
import logging
import os
import shutil
import sqlite3
import sys
import unittest
from typing import Dict, List, Optional, Tuple, Union

# Inject repository paths to allow imports to resolve correctly
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR: str = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "protos"))

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

try:
    import grid_telemetry_pb2 as pb2
    import grid_telemetry_pb2_grpc as pb2_grpc
except ImportError:
    # Compile protobuf stubs dynamically if needed
    import subprocess
    print("Compiling protobuf stubs...")
    subprocess.run([
        "python3", "-m", "grpc_tools.protoc",
        f"-I{ROOT_DIR}/protos",
        f"--python_out={ROOT_DIR}/protos",
        f"--grpc_python_out={ROOT_DIR}/protos",
        f"{ROOT_DIR}/protos/grid_telemetry.proto"
    ], check=True)
    import grid_telemetry_pb2 as pb2
    import grid_telemetry_pb2_grpc as pb2_grpc

from dashboard_modules.grpc_server import start_grpc_server
from dashboard_modules.grpc_client import GridTelemetryClient

# Ensure OLLAMA_HOST environment variable targets nvagent for the test run
os.environ["OLLAMA_HOST"] = os.environ.get("OLLAMA_HOST", "http://nvagent:11434")
os.environ["EDGE_MODEL"] = "gemma4-it-q4:latest"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class TestEscalationFlow(unittest.TestCase):
    """End-to-end integration test suite for microgrid anomaly escalation flow."""

    @classmethod
    def setUpClass(cls) -> None:
        """Sets up temporary database paths and starts the local gRPC server."""
        cls.test_backup_dir: str = os.path.join(SCRIPT_DIR, "test_backups")
        os.makedirs(cls.test_backup_dir, exist_ok=True)

        cls.test_grid_db: str = os.path.join(cls.test_backup_dir, "grid_history.db")
        cls.test_analysis_db: str = os.path.join(cls.test_backup_dir, "analysis_history.db")
        cls.test_escalations_json: str = os.path.join(cls.test_backup_dir, "escalations.json")

        # Clean existing test databases if present
        for path in [cls.test_grid_db, cls.test_analysis_db, cls.test_escalations_json]:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)

        # Copy production db/grid_history.db to our test folder to have historical data
        prod_db: str = os.path.join(ROOT_DIR, "db", "grid_history.db")
        if os.path.exists(prod_db):
            print(f"Copying production db to test database: {cls.test_grid_db}")
            shutil.copy2(prod_db, cls.test_grid_db)
        else:
            # Fallback schema creation
            print("No production database found. Initializing empty database.")
            conn = sqlite3.connect(cls.test_grid_db)
            conn.execute("CREATE TABLE grid_history (timestamp TEXT PRIMARY KEY, kw REAL)")
            conn.close()

        # Initialize the test analysis database
        conn = sqlite3.connect(cls.test_analysis_db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                timestamp TEXT PRIMARY KEY,
                baseline_timestamp TEXT NOT NULL,
                baseline_text TEXT,
                summary_text TEXT,
                dft_explanation TEXT,
                delta_import REAL NOT NULL,
                delta_export REAL NOT NULL,
                delta_peak REAL NOT NULL,
                delta_solar REAL NOT NULL,
                delta_se_solar REAL NOT NULL,
                delta_ch_solar REAL NOT NULL,
                delta_bat_charge REAL NOT NULL,
                delta_bat_discharge REAL NOT NULL,
                delta_se_load REAL NOT NULL,
                se_load_min REAL NOT NULL,
                se_load_max REAL NOT NULL,
                se_load_avg REAL NOT NULL,
                expected_temp_max REAL,
                expected_cloud_cover REAL,
                spectral_metrics_json TEXT,
                escalation_status INTEGER DEFAULT 0,
                escalation_timestamp TEXT
            )
        """)
        conn.close()

        # Point the cloud responder to our test JSON file
        from tests.emulation.mock_tier3_cloud import MockTier3CloudResponder
        cls.orig_init = MockTier3CloudResponder.__init__
        
        def patched_init(self_obj, audit_log_path: Optional[str] = None):
            cls.orig_init(self_obj, audit_log_path=cls.test_escalations_json)
            
        MockTier3CloudResponder.__init__ = patched_init

        # Start insecure gRPC server on port 50055
        cls.server_port: int = 50055
        cls.server = start_grpc_server(
            db_path=cls.test_grid_db,
            analysis_db_path=cls.test_analysis_db,
            port=cls.server_port,
            use_mtls=False
        )
        print(f"Test gRPC server running on localhost:{cls.server_port}")

        # Load fixture data
        fixture_path: str = os.path.join(SCRIPT_DIR, "ac_spike_fixture.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            cls.fixture = json.load(f)

    @classmethod
    def tearDownClass(cls) -> None:
        """Stops the gRPC server and cleans up test databases."""
        cls.server.stop(grace=None)
        print("Test gRPC server stopped.")
        
        # Restore original init method of MockTier3CloudResponder
        from tests.emulation.mock_tier3_cloud import MockTier3CloudResponder
        MockTier3CloudResponder.__init__ = cls.orig_init

        # Clean test directory
        if os.path.exists(cls.test_backup_dir):
            shutil.rmtree(cls.test_backup_dir)

    def _convert_readings(
        self, readings: List[Dict[str, Union[str, float]]]
    ) -> List[Tuple[datetime.datetime, float, float, float, float, float, float, float, float, float]]:
        """Utility to convert JSON readings into tuples for the gRPC client."""
        converted = []
        for r in readings:
            ts = datetime.datetime.fromisoformat(str(r["timestamp"]))
            converted.append((
                ts,
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
        return converted

    def test_01_clean_telemetry_flow(self) -> None:
        """Pushes clean telemetry and asserts no anomalies or escalations occur."""
        # Create a copy of the readings and ensure they are all normal/low load
        clean_readings = [dict(r) for r in self.fixture["readings"]]
        for r in clean_readings:
            r["grid_usage_kw"] = 1.25  # Force stable normal load
            r["solaredge_battery_kw"] = 0.0  # Idle battery, no RTE calculation triggered
            r["solaredge_battery_soc"] = 80.0
            r["solaredge_load_kw"] = 1.25  # Force stable normal house load

        packed = self._convert_readings(clean_readings)
        
        client = GridTelemetryClient(host="localhost", port=self.server_port, use_mtls=False)
        client.connect()
        try:
            success, message = client.evaluate_slice(
                slice_id="test_clean_slice",
                start_time=datetime.datetime.fromisoformat(self.fixture["start_timestamp"]),
                end_time=datetime.datetime.fromisoformat(self.fixture["end_timestamp"]),
                dft_period=1.0,
                readings=packed,
                spectral_metrics={"grid_bimodal_ratio": 0.5}  # Normal ratio
            )
            self.assertTrue(success)
            self.assertIn("Successfully inserted", message)
            self.assertNotIn("ANOMALY DETECTED", message)

            # Check that no escalations are logged in the database
            conn = sqlite3.connect(self.test_analysis_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM analysis_history WHERE escalation_status = 1")
            count = cursor.fetchone()[0]
            conn.close()
            self.assertEqual(count, 0)
        finally:
            client.close()

    def test_02_spike_anomaly_flow(self) -> None:
        """Pushes a high peak demand spike telemetry slice to trigger escalation."""
        anomalous_readings = [dict(r) for r in self.fixture["readings"]]
        # Inject peak demand spike
        anomalous_readings[len(anomalous_readings) // 2]["grid_usage_kw"] = 6.80

        packed = self._convert_readings(anomalous_readings)

        client = GridTelemetryClient(host="localhost", port=self.server_port, use_mtls=False)
        client.connect()
        try:
            success, message = client.evaluate_slice(
                slice_id="test_spike_slice",
                start_time=datetime.datetime.fromisoformat(self.fixture["start_timestamp"]),
                end_time=datetime.datetime.fromisoformat(self.fixture["end_timestamp"]),
                dft_period=1.0,
                readings=packed,
                spectral_metrics={"grid_bimodal_ratio": 0.5}
            )
            self.assertTrue(success)
            self.assertIn("ANOMALY DETECTED: Peak Demand Spike", message)
            self.assertIn("Escalated to Tier 3", message)

            # Check database for escalation status
            conn = sqlite3.connect(self.test_analysis_db)
            cursor = conn.cursor()
            cursor.execute("SELECT escalation_status, summary_text, dft_explanation FROM analysis_history WHERE escalation_status = 1")
            row = cursor.fetchone()
            conn.close()
            
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 1)
            # Verify the ReAct loop generated some analysis summary
            self.assertTrue(len(row[1]) > 0)
            print(f"Spike Analysis Summary: {row[1]}")

            # Verify local JSON audit log exists and contains the record
            self.assertTrue(os.path.exists(self.test_escalations_json))
            with open(self.test_escalations_json, "r", encoding="utf-8") as f:
                logs = json.load(f)
            self.assertTrue(any(log["slice_id"] == "test_spike_slice" for log in logs))
        finally:
            client.close()

    def test_03_battery_failure_flow(self) -> None:
        """Pushes low battery round-trip efficiency telemetry to trigger escalation."""
        anomalous_readings = [dict(r) for r in self.fixture["readings"]]
        
        # Inject low battery efficiency: charge heavily but discharge minimally
        for idx, r in enumerate(anomalous_readings):
            if idx % 2 == 0:
                r["solaredge_battery_kw"] = -4.0  # Charge heavily
            else:
                r["solaredge_battery_kw"] = 0.5   # Minimal discharge
            r["solaredge_battery_soc"] = 45.0
            r["solaredge_load_kw"] = 1.25  # Force stable normal house load

        packed = self._convert_readings(anomalous_readings)

        client = GridTelemetryClient(host="localhost", port=self.server_port, use_mtls=False)
        client.connect()
        try:
            success, message = client.evaluate_slice(
                slice_id="test_battery_slice",
                start_time=datetime.datetime.fromisoformat(self.fixture["start_timestamp"]),
                end_time=datetime.datetime.fromisoformat(self.fixture["end_timestamp"]),
                dft_period=1.0,
                readings=packed,
                spectral_metrics={"grid_bimodal_ratio": 0.5}
            )
            self.assertTrue(success)
            self.assertIn("ANOMALY DETECTED: Battery Inefficiency", message)

            # Check database for battery escalation status
            conn = sqlite3.connect(self.test_analysis_db)
            cursor = conn.cursor()
            cursor.execute("SELECT escalation_status, summary_text FROM analysis_history WHERE summary_text LIKE '%battery%' OR summary_text LIKE '%RTE%'")
            row = cursor.fetchone()
            conn.close()

            self.assertIsNotNone(row)
            print(f"Battery Analysis Summary: {row[1]}")
        finally:
            client.close()

    def test_04_peak_house_load_flow(self) -> None:
        """Pushes a high peak house load spike telemetry slice to trigger escalation."""
        anomalous_readings = [dict(r) for r in self.fixture["readings"]]
        # Inject peak house load spike
        for r in anomalous_readings:
            r["grid_usage_kw"] = 1.25  # Normal grid load
        anomalous_readings[len(anomalous_readings) // 2]["solaredge_load_kw"] = 7.50

        packed = self._convert_readings(anomalous_readings)

        client = GridTelemetryClient(host="localhost", port=self.server_port, use_mtls=False)
        client.connect()
        try:
            success, message = client.evaluate_slice(
                slice_id="test_house_load_slice",
                start_time=datetime.datetime.fromisoformat(self.fixture["start_timestamp"]),
                end_time=datetime.datetime.fromisoformat(self.fixture["end_timestamp"]),
                dft_period=1.0,
                readings=packed,
                spectral_metrics={"grid_bimodal_ratio": 0.5}
            )
            self.assertTrue(success)
            self.assertIn("ANOMALY DETECTED: Peak House Load Spike", message)
            self.assertIn("Escalated to Tier 3", message)

            # Check database for escalation status
            conn = sqlite3.connect(self.test_analysis_db)
            cursor = conn.cursor()
            cursor.execute("SELECT escalation_status, summary_text FROM analysis_history WHERE escalation_status = 1")
            row = cursor.fetchone()
            conn.close()

            self.assertIsNotNone(row)
            print(f"House Load Spike Summary: {row[1]}")
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()

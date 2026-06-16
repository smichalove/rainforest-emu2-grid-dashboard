"""Local gRPC pipeline emulation and verification script.

Spins up a local stager gRPC daemon on port 50051, inserts mock data,
queries the service via a loopback client, and asserts that serialization,
routing, and stream responses function correctly.
"""

import argparse
from concurrent import futures
import datetime
import logging
import os
import sys
import time
from typing import Generator, List, Tuple

# Inject repository paths to allow imports to resolve correctly
ROOT_DIR: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "protos"))

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

# import stub files that will be compiled
try:
    import grid_telemetry_pb2 as pb2
    import grid_telemetry_pb2_grpc as pb2_grpc
except ImportError:
    # Stubs will be compiled later in the execution sequence
    pb2 = None  # type: ignore
    pb2_grpc = None  # type: ignore

from tests.emulation.mock_database import (
    init_mock_databases,
    insert_mock_grid_reading,
    populate_mock_csvs,
)

# Global configuration variables
DEFAULT_EMULATION_PORT: int = 50051
DEFAULT_BACKUP_PATH: str = os.path.join(ROOT_DIR, "backups")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class EmulatedGridTelemetryService(pb2_grpc.GridTelemetryServiceServicer if pb2_grpc else object):
    """Local implementation of the GridTelemetryService for pipeline emulation."""

    def EvaluateTelemetrySlice(
        self, request: "pb2.TelemetrySlice", context: grpc.ServicerContext
    ) -> "pb2.TelemetryResponse":
        """Handles phase-aligned telemetry batch handover from client to server.

        Args:
            request: The incoming phase-aligned TelemetrySlice.
            context: gRPC execution context.

        Returns:
            TelemetryResponse confirming receipt.
        """
        logging.info(
            f"[Server] Received EvaluateTelemetrySlice for slice_id: {request.slice_id}"
        )
        logging.info(
            f"[Server] Ingested {len(request.readings)} readings. DFT Period: {request.dft_period_hours} hours."
        )
        return pb2.TelemetryResponse(
            success=True,
            message=f"Slice {request.slice_id} successfully processed with {len(request.readings)} readings.",
        )

    def GetTelemetryAnalysisStream(
        self, request: "pb2.AnalysisRequest", context: grpc.ServicerContext
    ) -> Generator["pb2.AnalysisStreamResponse", None, None]:
        """Streams LLM analysis response chunks back to the client display.

        Args:
            request: Prompt baseline details.
            context: gRPC execution context.

        Yields:
            AnalysisStreamResponse tokens representing the LLM generation.
        """
        logging.info("[Server] Initiating GetTelemetryAnalysisStream call...")

        # 1. Package and yield the initial quantitative metrics summary
        initial_analysis = pb2.AnalysisResponse(
            timestamp=self._get_now_pb_timestamp(),
            baseline_text=request.baseline_text,
            baseline_timestamp=request.baseline_timestamp,
            summary_text="Starting real-time analysis...",
            dft_explanation="Frequency metrics pending...",
            delta_import=2.45,
            delta_export=0.85,
            delta_peak=3.10,
            delta_solar=1.95,
            delta_se_solar=1.20,
            delta_ch_solar=0.75,
            delta_bat_charge=0.40,
            delta_bat_discharge=0.10,
            delta_se_load=2.85,
            expected_temp_max=21.0,
            expected_cloud_cover=40.0,
        )
        yield pb2.AnalysisStreamResponse(initial_analysis=initial_analysis)

        # 2. Simulate streaming tokens from Ollama (buffered server-side)
        mock_tokens: List[str] = [
            "Grid imports ",
            "remained elevated ",
            "due to cloud cover ",
            "modulating solar production.\n",
            "[DFT_START]",
            "Battery discharge ",
            "covered the peak load ",
            "successfully.",
        ]

        has_switched: bool = False
        for token in mock_tokens:
            time.sleep(0.2)  # Simulate small network/Ollama buffer delay
            if token == "[DFT_START]":
                has_switched = True
                continue
            if not has_switched:
                yield pb2.AnalysisStreamResponse(summary_token_chunk=token)
            else:
                yield pb2.AnalysisStreamResponse(dft_token_chunk=token)

        logging.info("[Server] GetTelemetryAnalysisStream complete.")

    def _get_now_pb_timestamp(self) -> Timestamp:
        """Helper to get current time as a Protobuf Timestamp.

        Returns:
            Current timestamp.
        """
        ts = Timestamp()
        ts.FromDatetime(datetime.datetime.now())
        return ts


def run_emulated_server(port: int) -> grpc.Server:
    """Spins up the local in-process gRPC stager server.

    Args:
        port: The local network port to bind the server to.

    Returns:
        The active running grpc.Server instance.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    pb2_grpc.add_GridTelemetryServiceServicer_to_server(
        EmulatedGridTelemetryService(), server
    )
    server.add_insecure_port(f"localhost:{port}")
    server.start()
    logging.info(f"Emulation server started on localhost:{port}")
    return server


def execute_client_queries(port: int) -> None:
    """Queries the emulation server using the loopback client channel.

    Args:
        port: Port of the running server.
    """
    logging.info(f"Connecting client to localhost:{port}...")
    with grpc.insecure_channel(f"localhost:{port}") as channel:
        stub = pb2_grpc.GridTelemetryServiceStub(channel)

        # 1. Test Telemetry ingestion
        now = datetime.datetime.now()
        ts_now = Timestamp()
        ts_now.FromDatetime(now)

        reading = pb2.TelemetryRequest(
            timestamp=ts_now,
            grid_usage_kw=1.52,
            solaredge_pv_kw=2.10,
            solaredge_battery_kw=-0.35,
            solaredge_battery_soc=78.2,
            solaredge_load_kw=1.85,
        )

        slice_req = pb2.TelemetrySlice(
            slice_id="emulated_slice_101",
            start_timestamp=ts_now,
            end_timestamp=ts_now,
            dft_period_hours=24.0,
            readings=[reading],
        )

        logging.info("[Client] Sending TelemetrySlice ingestion request...")
        ingest_resp = stub.EvaluateTelemetrySlice(slice_req)
        logging.info(f"[Client] Ingest response success: {ingest_resp.success}")
        logging.info(f"[Client] Ingest response message: {ingest_resp.message}")

        # Assert correct message loopback
        assert ingest_resp.success, "Telemetry ingestion failed in emulation"

        # 2. Test Analysis streaming
        analysis_req = pb2.AnalysisRequest(
            baseline_timestamp=ts_now,
            baseline_text="Local baseline test",
            batch_interval_hours=4,
        )

        logging.info("[Client] Requesting Analysis token stream...")
        stream_responses = stub.GetTelemetryAnalysisStream(analysis_req)

        # Iterate stream and log chunks
        for idx, resp in enumerate(stream_responses):
            if resp.HasField("initial_analysis"):
                init = resp.initial_analysis
                logging.info(
                    f"[Client] [Stream {idx}] Received initial metrics: Peak={init.delta_peak} kW, Solar={init.delta_solar} kWh"
                )
            if resp.summary_token_chunk:
                logging.info(
                    f"[Client] [Stream {idx}] Received summary token chunk: '{resp.summary_token_chunk}'"
                )
            if resp.dft_token_chunk:
                logging.info(
                    f"[Client] [Stream {idx}] Received DFT token chunk: '{resp.dft_token_chunk}'"
                )


def main() -> None:
    """Runs the emulation harness."""
    parser = argparse.ArgumentParser(description="Run gRPC edge stager emulation.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_EMULATION_PORT,
        help="Local port to bind emulation server to.",
    )
    args = parser.parse_args()

    if pb2 is None or pb2_grpc is None:
        logging.error("gRPC stubs are not compiled yet! Compile the proto file first.")
        sys.exit(1)

    # 1. Initialize mock databases
    logging.info("Initializing mock database directories...")
    init_mock_databases(DEFAULT_BACKUP_PATH)
    populate_mock_csvs(DEFAULT_BACKUP_PATH, ROOT_DIR)

    # Populate a few mock readings to verify DB loading
    now_iso = datetime.datetime.now().isoformat()
    insert_mock_grid_reading(
        os.path.join(DEFAULT_BACKUP_PATH, "grid_history.db"), now_iso, 1.250
    )

    # 2. Spin up server and run client calls
    server = run_emulated_server(args.port)
    try:
        execute_client_queries(args.port)
        logging.info("Emulation verification completed successfully!")
    finally:
        server.stop(grace=None)
        logging.info("Server shut down.")


if __name__ == "__main__":
    main()

"""Modular gRPC client for Project Antigravity.

Handles communication between Tier 1 (Pi Ingest Display) and Tier 2 (Jetson Server).
Manages SSL channel credentials configuration, loads client certificates from
the Auth/certs directory, handles secure/insecure loopbacks, and exposes APIs for
sending telemetry batches and reading streaming LLM response tokens.
"""

import datetime
import logging
import os
import sys
from typing import Generator, List, Optional, Tuple

# Inject repository paths to allow protobuf imports to resolve correctly
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR: str = os.path.dirname(SCRIPT_DIR)
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

# Global configurations
DEFAULT_HOST: str = "192.168.8.68"
DEFAULT_PORT: int = 50051
CERT_DIR_NAME: str = "Auth/certs"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def datetime_to_timestamp(dt: datetime.datetime) -> Timestamp:
    """Converts a standard Python datetime to a Protobuf Timestamp.

    Args:
        dt: The datetime instance to convert.

    Returns:
        Google Protobuf Timestamp object.
    """
    ts = Timestamp()
    ts.FromDatetime(dt)
    return ts


def timestamp_to_datetime(ts: Timestamp) -> datetime.datetime:
    """Converts a Protobuf Timestamp to a standard Python datetime.

    Args:
        ts: The Google Protobuf Timestamp object.

    Returns:
        Python datetime instance.
    """
    return ts.ToDatetime()


class GridTelemetryClient:
    """Encapsulates gRPC connection management and service request methods."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        use_mtls: bool = True,
        certs_dir: Optional[str] = None,
    ) -> None:
        """Initializes the gRPC client connection parameters.

        Args:
            host: Network address/IP of the Jetson server.
            port: Port of the Jetson gRPC service.
            use_mtls: Set to True to enable mutual TLS channel credentials.
            certs_dir: Path to directory containing ca.crt, client.crt, client.key.
        """
        self.host: str = host
        self.port: int = port
        self.use_mtls: bool = use_mtls
        self.certs_dir: str = certs_dir or os.path.join(ROOT_DIR, CERT_DIR_NAME)
        self.channel: Optional[grpc.Channel] = None
        self.stub: Optional[pb2_grpc.GridTelemetryServiceStub] = None

    def connect(self) -> None:
        """Establishes the secure or insecure gRPC channel and instantiates stubs.

        Raises:
            IOError: If certificates cannot be loaded for mTLS connection.
        """
        # Build the final network server endpoint address to bind the channel socket.
        server_address: str = f"{self.host}:{self.port}"

        if not self.use_mtls:
            # Fallback warning. Plaintext loopbacks are only utilized for local developer
            # workstation unit/contract test sandboxing. In production (edge display to Jetson),
            # unencrypted telemetry channels are forbidden.
            logging.warning(
                f"Establishing INSECURE plaintext channel to {server_address}"
            )
            self.channel = grpc.insecure_channel(server_address)
        else:
            # Initialize Mutual TLS (mTLS) zero-trust channel. We enforce peer certificate
            # verification on both sides (server verifies client, client verifies server) to
            # prevent address spoofing and telemetry ingestion interception.
            logging.info(
                f"Establishing SECURE mTLS channel to {server_address}..."
            )
            
            # Resolve certificate paths. Note that these files must be generated via generate_certs.py
            # and copied during deployment, and are strictly excluded from version control (.gitignore).
            ca_cert_path = os.path.join(self.certs_dir, "ca.crt")
            client_cert_path = os.path.join(self.certs_dir, "client.crt")
            client_key_path = os.path.join(self.certs_dir, "client.key")

            try:
                # Read certificate payloads. These are read as binary bytes directly to construct
                # the gRPC SSL credentials envelope.
                with open(ca_cert_path, "rb") as f:
                    ca_cert = f.read()
                with open(client_cert_path, "rb") as f:
                    client_cert = f.read()
                with open(client_key_path, "rb") as f:
                    client_key = f.read()

                # Bind credentials. gRPC handles SSL context wrapping and TLS handshake checks.
                # WARNING: In air-gapped/offline local microgrids, chrony/NTP must synchronize the Pi
                # display's clock with the Jetson edge server. If clock drift exceeds the certificate's
                # validity start/end window, gRPC will fail the handshake with a generic SSL error.
                credentials = grpc.ssl_channel_credentials(
                    root_certificates=ca_cert,
                    private_key=client_key,
                    certificate_chain=client_cert,
                )
                self.channel = grpc.secure_channel(server_address, credentials)
            except Exception as e:
                # Log critical trace information to simplify on-site kiosk debugging.
                logging.error(f"Failed to load certificate files for mTLS: {e}")
                raise IOError(f"Could not initialize mTLS credentials: {e}")

        # Bind the client stub to the established channel.
        self.stub = pb2_grpc.GridTelemetryServiceStub(self.channel)

    def close(self) -> None:
        """Closes the active connection channel."""
        if self.channel:
            self.channel.close()
            self.channel = None
            self.stub = None
            logging.info("gRPC channel closed.")

    def evaluate_slice(
        self,
        slice_id: str,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        dft_period: float,
        readings: List[Tuple[datetime.datetime, float, float, float, float, float, float, float, float, float]],
        spectral_metrics: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Packs and transmits a phase-aligned telemetry batch to the Jetson.

        Args:
            slice_id: Unique identifier for the batch.
            start_time: Start datetime of the telemetry slice window.
            end_time: End datetime of the telemetry slice window.
            dft_period: Dynamic window duration in hours calculated by FFT.
            readings: List of 10-tuples representing individual telemetry samples.
            spectral_metrics: Optional dict containing spectral and amplitude metrics.

        Returns:
            A tuple of (success_boolean, response_message_string).
        """
        if not self.stub:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Map readings list to TelemetryRequest messages
        proto_readings: List[pb2.TelemetryRequest] = []
        for r in readings:
            proto_readings.append(
                pb2.TelemetryRequest(
                    timestamp=datetime_to_timestamp(r[0]),
                    grid_usage_kw=r[1],
                    solaredge_pv_kw=r[2],
                    solaredge_battery_kw=r[3],
                    solaredge_battery_soc=r[4],
                    solaredge_load_kw=r[5],
                    solaredge_import_kw=r[6],
                    solaredge_export_kw=r[7],
                    chilicon_pv_kw=r[8],
                    chilicon_lifetime_wh=r[9],
                )
            )

        # Map spectral metrics dictionary to SpectralMetrics message
        proto_spectral = None
        if spectral_metrics:
            proto_spectral = pb2.SpectralMetrics(
                solar_24h_amp=spectral_metrics.get("solar_24h_amp", 0.0),
                solar_24h_peak_hour=spectral_metrics.get("solar_24h_peak_hour", 0.0),
                grid_24h_amp=spectral_metrics.get("grid_24h_amp", 0.0),
                grid_12h_amp=spectral_metrics.get("grid_12h_amp", 0.0),
                grid_12h_peak_hour=spectral_metrics.get("grid_12h_peak_hour", 0.0),
                grid_bimodal_ratio=spectral_metrics.get("grid_bimodal_ratio", 0.0),
                grid_24h_snr_db=spectral_metrics.get("grid_24h_snr_db", 0.0),
                grid_12h_snr_db=spectral_metrics.get("grid_12h_snr_db", 0.0),
                solar_24h_snr_db=spectral_metrics.get("solar_24h_snr_db", 0.0),
                consumption_24h_snr_db=spectral_metrics.get("consumption_24h_snr_db", 0.0),
                consumption_12h_snr_db=spectral_metrics.get("consumption_12h_snr_db", 0.0),
                solar_slope=spectral_metrics.get("solar_slope", 0.0),
                grid_slope=spectral_metrics.get("grid_slope", 0.0),
                freqs=spectral_metrics.get("freqs", []),
                grid_amp_spec=spectral_metrics.get("grid_amp_spec", []),
                solar_amp_spec=spectral_metrics.get("solar_amp_spec", []),
                consumption_amp_spec=spectral_metrics.get("consumption_amp_spec", []),
            )

        slice_request = pb2.TelemetrySlice(
            slice_id=slice_id,
            start_timestamp=datetime_to_timestamp(start_time),
            end_timestamp=datetime_to_timestamp(end_time),
            dft_period_hours=dft_period,
            readings=proto_readings,
            spectral_metrics=proto_spectral,
        )

        try:
            response = self.stub.EvaluateTelemetrySlice(slice_request)
            return response.success, response.message
        except grpc.RpcError as e:
            logging.error(f"gRPC EvaluateTelemetrySlice RPC error: {e}")
            return False, f"gRPC call failed: {e.details()}"

    def get_analysis_stream(
        self, baseline_text: str, baseline_time: datetime.datetime, interval_hours: int = 4
    ) -> Generator[pb2.AnalysisStreamResponse, None, None]:
        """Requests analysis streaming and yields token chunks as they arrive.

        Args:
            baseline_text: Summary text of the baseline historical context.
            baseline_time: Datetime of the baseline reference window.
            interval_hours: Size of the sliding analysis evaluation window.

        Yields:
            AnalysisStreamResponse tokens representing the LLM generation.
        """
        if not self.stub:
            raise RuntimeError("Client not connected. Call connect() first.")

        request = pb2.AnalysisRequest(
            baseline_timestamp=datetime_to_timestamp(baseline_time),
            baseline_text=baseline_text,
            batch_interval_hours=interval_hours,
        )

        try:
            stream_iter = self.stub.GetTelemetryAnalysisStream(request)
            for chunk in stream_iter:
                yield chunk
        except grpc.RpcError as e:
            logging.error(f"gRPC GetTelemetryAnalysisStream RPC error: {e}")
            raise

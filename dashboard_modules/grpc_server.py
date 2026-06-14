"""Modular gRPC server for Project Antigravity.

Runs on Tier 2 (Jetson Orin Nano Edge AI Server).
Loads server certificates/keys from the Auth/certs directory to enforce mutual TLS,
receives phase-aligned telemetry slices from the Pi, inserts readings into the SQLite
grid_history database, and feeds contexts to local LLM models (Ollama/Gemma) to
stream response chunks back to the client.
"""

import concurrent.futures
import datetime
import logging
import os
import sys
from typing import Callable, Generator, List, Optional, Tuple

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

from dashboard_modules.db import insert_reading

# Global configuration variables
DEFAULT_SERVER_PORT: int = 50051
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


class GridTelemetryService(pb2_grpc.GridTelemetryServiceServicer if pb2_grpc else object):
    """gRPC Servicer implementing the microgrid telemetry and analysis contract."""

    def __init__(
        self,
        db_path: str,
        analysis_db_path: str,
        calculate_metrics_fn: Optional[Callable] = None,
        query_ollama_stream_fn: Optional[Callable] = None,
        get_cached_spectrum_fn: Optional[Callable] = None,
    ) -> None:
        """Initializes the service with database paths, modeling functions, and cache getters.

        Args:
            db_path: Path to the SQLite grid telemetry history database.
            analysis_db_path: Path to the SQLite analysis history database.
            calculate_metrics_fn: Callback to execute mathematical modeling.
            query_ollama_stream_fn: Callback to stream Ollama generated tokens.
            get_cached_spectrum_fn: Callback to retrieve cached DFT spectrum dict.
        """
        # Save standard SQLite database endpoints needed for real-time sensor ingestion.
        self.db_path: str = db_path
        self.analysis_db_path: str = analysis_db_path
        
        # Save reference to the mathematical modeling workflow. This callback is executed
        # to calculate recent telemetry deltas, weather modulates, and construct the prompt
        # context right before invoking the LLM.
        self.calculate_metrics_fn: Optional[Callable] = calculate_metrics_fn
        
        # Save reference to the streaming local AI query generator. This callback interacts
        # directly with Ollama's stream generation APIs.
        self.query_ollama_stream_fn: Optional[Callable] = query_ollama_stream_fn
        
        # Save callback to fetch precomputed background spectrum data. Passing this as a callback
        # avoids direct module circular imports and preserves the clean modular layer separation
        # between the HTTP/gRPC server wrappers and the background stager daemon logic.
        self.get_cached_spectrum_fn: Optional[Callable] = get_cached_spectrum_fn

    def EvaluateTelemetrySlice(
        self, request: "pb2.TelemetrySlice", context: grpc.ServicerContext
    ) -> "pb2.TelemetryResponse":
        """Receives a phase-aligned batch of readings and inserts them into SQLite.

        Args:
            request: The incoming phase-aligned TelemetrySlice.
            context: gRPC execution context.

        Returns:
            TelemetryResponse indicating success.
        """
        logging.info(f"Received telemetry slice: {request.slice_id}")
        inserted_count: int = 0

        # Save each reading to the SQLite database
        for reading in request.readings:
            dt = timestamp_to_datetime(reading.timestamp)
            # Format to ISO string for storage compatibility
            dt_str: str = dt.isoformat()
            # Insert reading into SQLite using the db helper
            success: bool = insert_reading(self.db_path, dt_str, reading.grid_usage_kw)
            if success:
                inserted_count += 1

        msg: str = f"Successfully inserted {inserted_count}/{len(request.readings)} records from slice {request.slice_id}."
        logging.info(msg)
        return pb2.TelemetryResponse(success=True, message=msg)

    def GetTelemetryAnalysisStream(
        self, request: "pb2.AnalysisRequest", context: grpc.ServicerContext
    ) -> Generator["pb2.AnalysisStreamResponse", None, None]:
        """Queries local Ollama Gemma model and streams token responses back to the client.

        Args:
            request: The prompt details and baseline context parameters.
            context: gRPC execution context.

        Yields:
            AnalysisStreamResponse token packets.
        """
        logging.info("Initiating GetTelemetryAnalysisStream RPC call...")

        # 1. Convert baseline timestamp
        baseline_dt = timestamp_to_datetime(request.baseline_timestamp)
        baseline_ts_str = baseline_dt.strftime("%Y-%m-%d %H:%M:%S")

        # 2. Perform calculations
        if self.calculate_metrics_fn:
            try:
                analysis_data = self.calculate_metrics_fn(
                    baseline_ts_str, request.baseline_text, request.batch_interval_hours
                )
            except Exception as e:
                logging.error(f"Error calculating analysis metrics: {e}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"Math modeling failure: {str(e)}")
                return
        else:
            # Fallback mock if callbacks are not registered
            analysis_data = {
                "temp_max": 21.0,
                "cloud_cover": 40.0,
                "delta_peak": 3.10,
                "delta_solar": 1.95,
                "formatted_prompt": "Mock prompt...",
                "formatted_dft_prompt": "Mock DFT prompt...",
            }

        # 3. Query the background stager cache to retrieve the full-history DFT spectrum
        # precomputed in the background. Slicing and rendering a DTFT spectrum of 89,000+
        # data points on a Raspberry Pi kiosk will cause severe lag or a UI crash. Doing it
        # on the Jetson Orin Nano's GPU-enabled background thread pool and sending it down
        # as part of this response completely offloads the computation.
        proto_spectral = None
        if self.get_cached_spectrum_fn:
            try:
                spec_data = self.get_cached_spectrum_fn()
                if spec_data and "freqs" in spec_data:
                    # Construct the SpectralMetrics sub-message. We map the calculated amplitudes
                    # and weather modulations directly to the corresponding Protobuf fields.
                    proto_spectral = pb2.SpectralMetrics(
                        freqs=spec_data["freqs"],
                        grid_amp_spec=spec_data["grid_amp"],
                        solar_amp_spec=spec_data["solar_amp"],
                        consumption_amp_spec=spec_data["consumption_amp"],
                        expected_solar_amp_spec=spec_data["expected_solar_amp"]
                    )
                    logging.info("Successfully packed full-history DFT spectrum into gRPC response.")
            except Exception as e:
                # Log non-fatal caching errors so that telemetry summary continues to work
                # even if the background math thread encountered an issue.
                logging.error(f"Error packing cached spectrum for gRPC response: {e}")

        # 4. Construct and yield the initial quantitative metrics summary.
        # This acts as the first frame in the server stream, containing all statistical
        # variables, weather forecast predictors, and the precomputed spectral arrays.
        initial_analysis = pb2.AnalysisResponse(
            timestamp=datetime_to_timestamp(datetime.datetime.now()),
            baseline_text=analysis_data.get("baseline_text", request.baseline_text),
            baseline_timestamp=datetime_to_timestamp(
                datetime.datetime.strptime(
                    analysis_data.get("baseline_timestamp", baseline_ts_str),
                    "%Y-%m-%d %H:%M:%S"
                )
            ),
            summary_text="Starting real-time analysis...",
            dft_explanation="Pending spectral evaluation...",
            delta_import=analysis_data.get("delta_import", 0.0),
            delta_export=analysis_data.get("delta_export", 0.0),
            delta_peak=analysis_data.get("delta_peak", 0.0),
            delta_solar=analysis_data.get("delta_solar", 0.0),
            delta_se_solar=analysis_data.get("delta_se_solar", 0.0),
            delta_ch_solar=analysis_data.get("delta_ch_solar", 0.0),
            delta_bat_charge=analysis_data.get("delta_bat_charge", 0.0),
            delta_bat_discharge=analysis_data.get("delta_bat_discharge", 0.0),
            delta_se_load=analysis_data.get("delta_se_load", 0.0),
            expected_temp_max=analysis_data.get("temp_max", 0.0),
            expected_cloud_cover=analysis_data.get("cloud_cover", 0.0),
            spectral_metrics=proto_spectral,
        )
        yield pb2.AnalysisStreamResponse(initial_analysis=initial_analysis)

        # 4. Stream summary tokens from local Ollama Gemma
        model_name: str = os.environ.get("EDGE_MODEL", "gemma4-it-q4")
        if self.query_ollama_stream_fn:
            logging.info("Streaming time-domain analysis tokens...")
            try:
                for token in self.query_ollama_stream_fn(
                    analysis_data["formatted_prompt"], model_name
                ):
                    yield pb2.AnalysisStreamResponse(summary_token_chunk=token)
            except Exception as e:
                logging.error(f"Error streaming time-domain summary: {e}")

            logging.info("Streaming frequency-domain analysis tokens...")
            try:
                for token in self.query_ollama_stream_fn(
                    analysis_data["formatted_dft_prompt"], model_name
                ):
                    yield pb2.AnalysisStreamResponse(dft_token_chunk=token)
            except Exception as e:
                logging.error(f"Error streaming DFT explanation: {e}")
        else:
            # Fallback mock token stream if callback is missing
            mock_tokens: List[str] = [
                "This ",
                "is ",
                "a ",
                "fallback ",
                "streaming ",
                "response.",
            ]
            for token in mock_tokens:
                time.sleep(0.1)
                yield pb2.AnalysisStreamResponse(summary_token_chunk=token)


def start_grpc_server(
    db_path: str,
    analysis_db_path: str,
    calculate_metrics_fn: Optional[Callable] = None,
    query_ollama_stream_fn: Optional[Callable] = None,
    get_cached_spectrum_fn: Optional[Callable] = None,
    port: int = DEFAULT_SERVER_PORT,
    use_mtls: bool = True,
    certs_dir: Optional[str] = None,
) -> grpc.Server:
    """Starts the gRPC service with the configured secure/insecure credentials.

    Args:
        db_path: Path to the SQLite grid telemetry history database.
        analysis_db_path: Path to the SQLite analysis history database.
        calculate_metrics_fn: Callback to execute mathematical modeling.
        query_ollama_stream_fn: Callback to stream Ollama generated tokens.
        get_cached_spectrum_fn: Callback to retrieve cached DFT spectrum dict.
        port: Listening port.
        use_mtls: Set to True to enable mutual TLS channel credentials.
        certs_dir: Path to folder containing ca.crt, server.crt, and server.key.

    Returns:
        The running grpc.Server instance.
    """
    # Instantiate the standard gRPC server using a ThreadPoolExecutor with a pool size
    # of 10 workers. This ensures that concurrent connections (e.g. parallel sensor
    # ingestion streams and interactive LLM token queries) can be resolved concurrently
    # without blockages or task starvation.
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_GridTelemetryServiceServicer_to_server(
        GridTelemetryService(
            db_path,
            analysis_db_path,
            calculate_metrics_fn,
            query_ollama_stream_fn,
            get_cached_spectrum_fn
        ),
        server
    )

    server_address: str = f"[::]:{port}"

    if not use_mtls:
        logging.warning(f"Binding INSECURE server listener to {server_address}")
        server.add_insecure_port(server_address)
    else:
        logging.info(f"Binding SECURE mTLS server listener to {server_address}...")
        certs_path = certs_dir or os.path.join(ROOT_DIR, CERT_DIR_NAME)

        ca_cert_path = os.path.join(certs_path, "ca.crt")
        server_cert_path = os.path.join(certs_path, "server.crt")
        server_key_path = os.path.join(certs_path, "server.key")

        try:
            with open(ca_cert_path, "rb") as f:
                ca_cert = f.read()
            with open(server_cert_path, "rb") as f:
                server_cert = f.read()
            with open(server_key_path, "rb") as f:
                server_key = f.read()

            # Set up server SSL credentials (requiring client certificate authentication)
            server_credentials = grpc.ssl_server_credentials(
                [(server_key, server_cert)],
                root_certificates=ca_cert,
                require_client_auth=True,
            )
            server.add_secure_port(server_address, server_credentials)
        except Exception as e:
            logging.error(f"Failed to load certificate files for server mTLS: {e}")
            raise IOError(f"Could not initialize server mTLS credentials: {e}")

    server.start()
    logging.info(f"gRPC server successfully started on {server_address}")
    return server

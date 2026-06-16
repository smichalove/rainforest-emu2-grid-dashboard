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
import time
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

from dashboard_modules.db import insert_reading, insert_analysis_history

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

    def _calculate_grid_stats(self) -> Tuple[float, float]:
        """Calculates historical mean and standard deviation of grid demand using SQL.

        Returns:
            A tuple of (mean, standard_deviation).
        """
        import sqlite3
        import math
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(kw), COUNT(*) FROM grid_history")
            row = cursor.fetchone()
            if not row or not row[1]:
                conn.close()
                return 0.0, 1.0
            avg_kw, count = float(row[0]), int(row[1])
            if count <= 1:
                conn.close()
                return avg_kw, 1.0
            # Calculate variance using SQL to avoid pulling all records
            cursor.execute("SELECT SUM((kw - ?) * (kw - ?)) FROM grid_history", (avg_kw, avg_kw))
            sum_sq_diff_row = cursor.fetchone()
            conn.close()
            
            if sum_sq_diff_row and sum_sq_diff_row[0] is not None:
                var_val = float(sum_sq_diff_row[0]) / (count - 1)
                std_val = math.sqrt(var_val)
            else:
                std_val = 1.0
            return avg_kw, std_val
        except Exception as e:
            logging.error(f"Error calculating grid stats on server: {e}")
            return 0.0, 1.0

    def _calculate_house_load_stats(self) -> Tuple[float, float]:
        """Calculates historical mean and standard deviation of house load using SQL.

        Returns:
            A tuple of (mean, standard_deviation) representing the historical
            average house load and the load standard deviation (noise floor).
        """
        import sqlite3
        import math
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(load_power_kw), COUNT(*) FROM solaredge_flow_history")
            row = cursor.fetchone()
            if not row or not row[1]:
                conn.close()
                return 0.0, 1.0
            avg_load, count = float(row[0]), int(row[1])
            if count <= 1:
                conn.close()
                return avg_load, 1.0
            # Calculate variance using SQL to avoid pulling all records
            cursor.execute("SELECT SUM((load_power_kw - ?) * (load_power_kw - ?)) FROM solaredge_flow_history", (avg_load, avg_load))
            sum_sq_diff_row = cursor.fetchone()
            conn.close()
            
            if sum_sq_diff_row and sum_sq_diff_row[0] is not None:
                var_val = float(sum_sq_diff_row[0]) / (count - 1)
                std_val = math.sqrt(var_val)
            else:
                std_val = 1.0
            return avg_load, std_val
        except Exception as e:
            logging.error(f"Error calculating house load stats on server: {e}")
            return 0.0, 1.0

    def _evaluate_anomalies(
        self, request: "pb2.TelemetrySlice"
    ) -> Tuple[bool, str, dict]:
        """Evaluates the incoming slice for anomalies using predefined threshold rules.

        Rules:
        - Grid Peak Demand Anomaly: z_score_peak > 3.0.
        - Peak House Load Spike Check: z_score_load > 3.0.
        - Battery Inefficiency: RTE < 65% during charge/discharge.
        - Spectral Rhythm Disruption: Bimodality ratio falling outside [0.3, 0.7].

        Args:
            request: The incoming TelemetrySlice.

        Returns:
            A tuple of (is_anomalous, anomaly_type_string, trigger_metrics_dict).
        """
        readings = request.readings
        if not readings:
            return False, "", {}

        # 1. Peak Demand Spike Check
        peak_kw: float = max(r.grid_usage_kw for r in readings)
        grid_mean, grid_std = self._calculate_grid_stats()
        z_score_peak: float = 0.0
        if grid_std > 0:
            z_score_peak = (peak_kw - grid_mean) / grid_std

        if z_score_peak > 3.0:
            return True, "Peak Demand Spike", {"peak_kw": peak_kw, "z_score_peak": z_score_peak}

        # 1b. Peak House Load Spike Check
        peak_load: float = max(r.solaredge_load_kw for r in readings) if readings else 0.0
        load_mean, load_std = self._calculate_house_load_stats()
        z_score_load: float = 0.0
        if load_std > 0:
            z_score_load = (peak_load - load_mean) / load_std

        if z_score_load > 3.0:
            return True, "Peak House Load Spike", {"peak_load": peak_load, "z_score_load": z_score_load}

        # 2. Battery Inefficiency Check
        delta_bat_charge: float = 0.0
        delta_bat_discharge: float = 0.0
        
        # Calculate battery deltas from slice readings
        for i in range(len(readings) - 1):
            r_curr = readings[i]
            r_next = readings[i+1]
            t_curr = timestamp_to_datetime(r_curr.timestamp)
            t_next = timestamp_to_datetime(r_next.timestamp)
            dt_hours: float = (t_next - t_curr).total_seconds() / 3600.0
            
            # Avoid long gaps distorting metrics
            if 0 < dt_hours <= 1.0:
                p_val: float = r_curr.solaredge_battery_kw
                if p_val > 0:
                    delta_bat_discharge += p_val * dt_hours
                elif p_val < 0:
                    delta_bat_charge += abs(p_val) * dt_hours

        # Calculate RTE if there was active charging
        if delta_bat_charge > 0.05:  # Require minimum charge accumulation to avoid noise
            battery_rte: float = (delta_bat_discharge / delta_bat_charge) * 100.0  # Percentage
            if battery_rte < 65.0:
                return True, "Battery Inefficiency", {
                    "battery_rte": battery_rte,
                    "delta_bat_charge": delta_bat_charge,
                    "delta_bat_discharge": delta_bat_discharge,
                }

        # 3. Spectral Rhythm Disruption Check
        if request.HasField("spectral_metrics"):
            bimodal: float = request.spectral_metrics.grid_bimodal_ratio
            if bimodal > 0 and (bimodal < 0.3 or bimodal > 0.7):
                return True, "Spectral Rhythm Disruption", {"grid_bimodal_ratio": bimodal}

        return False, "", {}

    def EvaluateTelemetrySlice(
        self, request: "pb2.TelemetrySlice", context: grpc.ServicerContext
    ) -> "pb2.TelemetryResponse":
        """Receives a phase-aligned batch of readings and inserts them into SQLite.

        Also runs threshold anomaly detection checks. If anomalies are flagged,
        records them in analysis_history.db and escalates to Tier 3 cloud support.

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

        base_msg: str = f"Successfully inserted {inserted_count}/{len(request.readings)} records from slice {request.slice_id}."
        logging.info(base_msg)

        # Run anomaly detection rules
        is_anomalous, anomaly_type, trigger_metrics = self._evaluate_anomalies(request)
        if is_anomalous:
            logging.warning(
                f"[Server] MICROGRID ANOMALY DETECTED: {anomaly_type}. Initiating Tier 3 escalation..."
            )
            import json
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Run the Agentic SQL Tool Loop to generate a detailed local diagnostic summary first!
            agent_diagnostic_summary = ""
            try:
                from dashboard_modules.agent_loop import run_agentic_sql_loop
                peak_kw_val = max(r.grid_usage_kw for r in request.readings) if request.readings else 0.0
                peak_load_val = max(r.solaredge_load_kw for r in request.readings) if request.readings else 0.0
                bimodal_val = request.spectral_metrics.grid_bimodal_ratio if request.HasField("spectral_metrics") else 0.0
                rte_val = trigger_metrics.get("battery_rte", 0.0)
                grid_mean_val, grid_std_val = self._calculate_grid_stats()
                house_mean_val, house_std_val = self._calculate_house_load_stats()
                
                logging.info("[Server] Launching local edge Agentic SQL tool execution loop...")
                agent_diagnostic_summary = run_agentic_sql_loop(
                    db_path=self.db_path,
                    anomaly_type=anomaly_type,
                    peak_kw=peak_kw_val,
                    peak_load=peak_load_val,
                    bimodal_ratio=bimodal_val,
                    rte=rte_val,
                    grid_mean=grid_mean_val,
                    grid_std=grid_std_val,
                    house_mean=house_mean_val,
                    house_std=house_std_val,
                    model=os.environ.get("EDGE_MODEL", "gemma4-it-q4:latest")
                )
                logging.info(f"[Server] Agentic SQL loop completed. Summary:\n{agent_diagnostic_summary}")
            except Exception as loop_err:
                logging.error(f"[Server] Agentic SQL loop encountered an error: {loop_err}")
                agent_diagnostic_summary = f"Local Edge Agentic SQL Loop failed: {loop_err}"

            # Invoke the Cloud Mock Responder
            try:
                from tests.emulation.mock_tier3_cloud import MockTier3CloudResponder
                cloud_responder = MockTier3CloudResponder()
                cloud_resp = cloud_responder.process_escalation(
                    request.slice_id,
                    anomaly_type,
                    {**trigger_metrics, "agent_summary": agent_diagnostic_summary}
                )
                summary_text = agent_diagnostic_summary if agent_diagnostic_summary else cloud_resp.get("cloud_diagnostic_summary", "Cloud diagnosis failed.")
                dft_explanation = cloud_resp.get("action_recommendation", "")
            except Exception as e:
                logging.error(f"Error invoking cloud mock responder: {e}")
                summary_text = f"Failed to invoke cloud responder. Error: {e}"
                dft_explanation = ""

            # Construct analysis_history database record
            peak_kw: float = max(r.grid_usage_kw for r in request.readings) if request.readings else 0.0
            # Prepend a clear audit header so the kiosk dashboard displays when the agent ran
            agent_header = f"[Edge Agent analyzed anomaly at {now_str}]:\n"
            record = {
                "timestamp": now_str,
                "baseline_timestamp": now_str,
                "baseline_text": f"Anomaly Triggered: {anomaly_type}",
                "summary_text": agent_header + summary_text,
                "dft_explanation": dft_explanation,
                "delta_import": 0.0,
                "delta_export": 0.0,
                "delta_peak": peak_kw,
                "delta_solar": 0.0,
                "delta_se_solar": 0.0,
                "delta_ch_solar": 0.0,
                "delta_bat_charge": trigger_metrics.get("delta_bat_charge", 0.0),
                "delta_bat_discharge": trigger_metrics.get("delta_bat_discharge", 0.0),
                "delta_se_load": 0.0,
                "se_load_min": 0.0,
                "se_load_max": 0.0,
                "se_load_avg": 0.0,
                "expected_temp_max": 0.0,
                "expected_cloud_cover": 0.0,
                "spectral_metrics_json": json.dumps(trigger_metrics),
                "escalation_status": 1,
                "escalation_timestamp": now_str,
            }
            
            db_logged = False
            if self.analysis_db_path:
                try:
                    db_logged = insert_analysis_history(self.analysis_db_path, record)
                except Exception as db_err:
                    logging.error(f"Error inserting escalation record to analysis db: {db_err}")

            escalation_msg = (
                f"{base_msg} ANOMALY DETECTED: {anomaly_type}. "
                f"Escalated to Tier 3 cloud diagnostics. Logged to DB: {db_logged}."
            )
            logging.info(f"[Server] {escalation_msg}")
            return pb2.TelemetryResponse(success=True, message=escalation_msg)

        return pb2.TelemetryResponse(success=True, message=base_msg)

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

        # 4. Stream Slide 1 summary followed by Slide 3 DFT explanation
        model_name: str = os.environ.get("EDGE_MODEL", "gemma4-it-q4")
        summary_text_accum = []
        dft_explanation_accum = []

        if self.query_ollama_stream_fn:
            logging.info("Streaming Slide 1 summary tokens...")
            try:
                for token in self.query_ollama_stream_fn(
                    analysis_data["formatted_prompt"], model_name
                ):
                    summary_text_accum.append(token)
                    yield pb2.AnalysisStreamResponse(summary_token_chunk=token)
            except Exception as e:
                logging.error(f"Error streaming Slide 1 summary: {e}")

            logging.info("Streaming Slide 3 DFT explanation tokens...")
            try:
                for token in self.query_ollama_stream_fn(
                    analysis_data["formatted_dft_prompt"], model_name
                ):
                    dft_explanation_accum.append(token)
                    yield pb2.AnalysisStreamResponse(dft_token_chunk=token)
            except Exception as e:
                logging.error(f"Error streaming Slide 3 DFT explanation: {e}")
        else:
            # Fallback mock token stream matching the sequential structure
            mock_summary_tokens: List[str] = [
                "This ", "is ", "a ", "fallback ", "streaming ", "time-domain ", "summary."
            ]
            mock_dft_tokens: List[str] = [
                "This ", "is ", "a ", "fallback ", "layman ", "DFT ", "explanation."
            ]
            for token in mock_summary_tokens:
                time.sleep(0.05)
                summary_text_accum.append(token)
                yield pb2.AnalysisStreamResponse(summary_token_chunk=token)
            for token in mock_dft_tokens:
                time.sleep(0.05)
                dft_explanation_accum.append(token)
                yield pb2.AnalysisStreamResponse(dft_token_chunk=token)

        # 5. Insert completed analysis record into the SQLite database
        import json
        summary_text: str = "".join(summary_text_accum)
        dft_explanation: str = "".join(dft_explanation_accum)

        record = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "baseline_timestamp": analysis_data.get("baseline_timestamp", baseline_ts_str),
            "baseline_text": analysis_data.get("baseline_text", request.baseline_text),
            "summary_text": summary_text,
            "dft_explanation": dft_explanation,
            "delta_import": analysis_data.get("delta_import", 0.0),
            "delta_export": analysis_data.get("delta_export", 0.0),
            "delta_peak": analysis_data.get("delta_peak", 0.0),
            "delta_solar": analysis_data.get("delta_solar", 0.0),
            "delta_se_solar": analysis_data.get("delta_se_solar", 0.0),
            "delta_ch_solar": analysis_data.get("delta_ch_solar", 0.0),
            "delta_bat_charge": analysis_data.get("delta_bat_charge", 0.0),
            "delta_bat_discharge": analysis_data.get("delta_bat_discharge", 0.0),
            "delta_se_load": analysis_data.get("delta_se_load", 0.0),
            "se_load_min": analysis_data.get("se_load_min", 0.0),
            "se_load_max": analysis_data.get("se_load_max", 0.0),
            "se_load_avg": analysis_data.get("se_load_avg", 0.0),
            "expected_temp_max": analysis_data.get("temp_max", 0.0),
            "expected_cloud_cover": analysis_data.get("cloud_cover", 0.0),
            "spectral_metrics_json": json.dumps({
                "solar_24h_amp": analysis_data.get("solar_24h_amp", 0.0),
                "solar_24h_peak_hour": analysis_data.get("solar_24h_peak_hour", 0.0),
                "se_24h_peak_hour": analysis_data.get("se_24h_peak_hour", 0.0),
                "ch_24h_peak_hour": analysis_data.get("ch_24h_peak_hour", 0.0),
                "grid_bimodal_ratio": analysis_data.get("grid_bimodal_ratio", 0.0),
                "solar_slope": analysis_data.get("solar_slope", 0.0),
                "grid_slope": analysis_data.get("grid_slope", 0.0),
                "grid_24h_snr_db": analysis_data.get("grid_24h_snr_db", 0.0),
                "grid_12h_snr_db": analysis_data.get("grid_12h_snr_db", 0.0),
                "solar_24h_snr_db": analysis_data.get("solar_24h_snr_db", 0.0),
                "consumption_24h_snr_db": analysis_data.get("consumption_24h_snr_db", 0.0),
                "consumption_12h_snr_db": analysis_data.get("consumption_12h_snr_db", 0.0),
                "z_score_peak": analysis_data.get("z_score_peak", 0.0),
                "battery_rte": analysis_data.get("battery_rte", 0.0),
                "solar_correlation": analysis_data.get("solar_correlation", 0.0),
                "daylight_duration": analysis_data.get("daylight_duration", 0.0)
            }),
            "escalation_status": 0,
            "escalation_timestamp": None
        }

        if self.analysis_db_path:
            try:
                success = insert_analysis_history(self.analysis_db_path, record)
                if success:
                    logging.info(f"Successfully logged gRPC streaming analysis to SQLite database at {self.analysis_db_path}")
                else:
                    logging.error(f"Failed to log gRPC streaming analysis to SQLite database at {self.analysis_db_path}")
            except Exception as db_err:
                logging.error(f"Error logging gRPC streaming analysis to database: {db_err}")


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
